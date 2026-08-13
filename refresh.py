#!/usr/bin/env python3
"""Refreshes data.json with current Sopron hotel rankings/prices from the
Tripadvisor Terra API (https://docs.terra.tripadvisor.com/docs/overview).

Run by the "Refresh Sopron hotel prices" GitHub Actions workflow daily.
data.json is fetched by the hotel showcase widget on bestofsopron.eu via
raw.githubusercontent.com - this script is the only thing that writes it.

Base URL is per Tripadvisor's own docs (relayed by the repo owner - this
sandbox can't reach terra.tripadvisor.com to verify directly):
    https://terra.tripadvisor.com/api
A first real run against POST /recommendations/search confirmed that host
and path are reachable (a clean 401, not a connection/DNS error), but
every doc source has disagreed on the auth scheme, and the first attempt
(X-Tripadvisor-API-Key header) was rejected. Since this sandbox can't
dispatch the workflow itself - each guess costs the repo owner a manual
click - send_request() now tries several plausible schemes in one run
(see _auth_candidates()) and reports in the log which one, if any, got
past authentication. Once one works, pin it via TRIPADVISOR_AUTH_MODE so
future runs don't need to retry them all.

Neither doc source documented pricing as a returned field (Location/
Reviews/Photos/Geo/Recommendations only were listed) - Tripadvisor's live
per-night pricing is typically a separate sponsored-placement feed, not
part of the general Partner API. Until that's confirmed one way or the
other, parse_hotel() below keeps each hotel's previous price rather than
zeroing it out if the response has no price field, and rank/rating/review
data updates normally.

Required environment variable:
    TRIPADVISOR_API_KEY  Your Terra/Partner API key.

Optional environment variables:
    TRIPADVISOR_TERRA_BASE_URL  Overrides the default base URL above.
    TRIPADVISOR_AUTH_MODE        Pin to one scheme instead of trying all of
                                  them: "header:X-Tripadvisor-API-Key",
                                  "header:X-API-Key", "query:key", or
                                  "header:Authorization-Bearer".
    SOPRON_LOCATION               Defaults to "Sopron, Hungary".
    SOPRON_CHECK_IN                YYYY-MM-DD, defaults to 14 days from today.
    SOPRON_NIGHTS                  Defaults to 1.

TODO once the /recommendations/search request/response schema is fully
confirmed: verify the request payload below and the field names
parse_hotel() reads match a real response (check the workflow run logs).

On any failure this script exits non-zero WITHOUT touching data.json, so a
broken run never wipes out the last known-good feed the live site depends on.
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

DATA_PATH = Path(__file__).parent / "data.json"
DEFAULT_BASE_URL = "https://terra.tripadvisor.com/api"

LOCATION = os.environ.get("SOPRON_LOCATION", "Sopron, Hungary")
CHECK_IN = os.environ.get(
    "SOPRON_CHECK_IN", (date.today() + timedelta(days=14)).isoformat()
)
NIGHTS = int(os.environ.get("SOPRON_NIGHTS", "1"))
CHECK_OUT = (date.fromisoformat(CHECK_IN) + timedelta(days=NIGHTS)).isoformat()
ADULTS = 2
ROOMS = 1


def _thumbnail_url(hotel: dict) -> str:
    template = (
        hotel.get("thumbnail", {}).get("photoSizeDynamic", {}).get("urlTemplate", "")
    )
    if template:
        return template.replace("{width}", "400").replace("{height}", "300")
    photo_sizes = hotel.get("thumbnail", {}).get("photoSizes", [])
    return photo_sizes[-1]["url"] if photo_sizes else ""


def _tripadvisor_url(hotel: dict) -> str:
    path = hotel.get("hotelReviewUrl", "")
    if path.startswith("http"):
        return path
    return f"https://www.tripadvisor.com{path}"


def parse_hotel(rank: int, hotel: dict, previous_by_id: dict) -> dict:
    price_info = hotel.get("priceInfo") or {}
    review = hotel.get("reviewSummary") or {}
    styles = [
        s["styleName"]
        for s in hotel.get("locationV2", {}).get("hotelStyleRankings", [])
    ]
    hotel_id = hotel.get("hotelId") or hotel.get("location_id")
    previous = previous_by_id.get(hotel_id, {})

    def _to_amount(value) -> float:
        if value in (None, ""):
            return None
        if isinstance(value, str):
            value = value.replace("$", "").replace(",", "")
        return float(value)

    price_from = _to_amount(price_info.get("displayPrice", ""))
    taxes = _to_amount(price_info.get("displayTaxesAndFees", ""))

    return {
        "rank": rank,
        "hotelId": hotel_id,
        "name": hotel.get("hotelName") or hotel.get("name", "Unknown Hotel"),
        "rating": review.get("rating", previous.get("rating", 0)),
        "reviewCount": review.get("count", previous.get("reviewCount", 0)),
        # Falls back to the last known price if this response has none -
        # see the pricing caveat in the module docstring.
        "priceFrom": price_from if price_from is not None else previous.get("priceFrom", 0),
        "taxesAndFees": taxes if taxes is not None else previous.get("taxesAndFees", 0),
        "styles": styles[:3] or previous.get("styles", []),
        "thumbnail": _thumbnail_url(hotel) or previous.get("thumbnail", ""),
        "tripadvisorUrl": _tripadvisor_url(hotel) or previous.get("tripadvisorUrl", ""),
    }


def _auth_candidates(api_key: str):
    """(name, extra_headers, extra_params) for each auth scheme worth
    trying. Every doc source so far has disagreed on the exact scheme, and
    each manual test costs the repo owner a round trip (this sandbox can't
    dispatch the workflow itself), so a failed run tries all of them in one
    go and reports which - if any - actually got past authentication."""
    return [
        ("header:X-Tripadvisor-API-Key", {"X-Tripadvisor-API-Key": api_key}, None),
        ("header:X-API-Key", {"X-API-Key": api_key}, None),
        ("query:key", {}, {"key": api_key}),
        ("header:Authorization-Bearer", {"Authorization": f"Bearer {api_key}"}, None),
    ]


def send_request(base_url: str, api_key: str) -> dict:
    url = f"{base_url.rstrip('/')}/recommendations/search"
    payload = {
        "location": LOCATION,
        "checkIn": CHECK_IN,
        "checkOut": CHECK_OUT,
        "guests": ADULTS,
        "rooms": ROOMS,
        "sortBy": "POPULARITY",
        "limit": 20,
    }

    requested_mode = os.environ.get("TRIPADVISOR_AUTH_MODE", "").strip()
    candidates = _auth_candidates(api_key)
    if requested_mode:
        candidates = [c for c in candidates if c[0] == requested_mode]
        if not candidates:
            sys.exit(
                f"TRIPADVISOR_AUTH_MODE={requested_mode!r} doesn't match any "
                f"known scheme: {[c[0] for c in _auth_candidates(api_key)]}"
            )

    attempts = []
    for name, extra_headers, params in candidates:
        headers = {"Content-Type": "application/json", **extra_headers}
        response = requests.post(url, headers=headers, params=params, json=payload, timeout=30)
        if response.status_code in (401, 403):
            attempts.append(f"{name}: {response.status_code} {response.text[:200]!r}")
            continue
        print(f"Auth scheme '{name}' got past authentication (status {response.status_code}).")
        response.raise_for_status()
        return response.json()

    sys.exit(
        "All auth schemes were rejected (401/403) by "
        + url
        + ":\n"
        + "\n".join(attempts)
        + "\nThe key itself may be inactive/wrong for this endpoint - check the Terra dashboard."
    )


def fetch_hotels(previous_by_id: dict) -> list:
    api_key = os.environ.get("TRIPADVISOR_API_KEY")
    if not api_key:
        sys.exit("Set TRIPADVISOR_API_KEY before running this script.")
    base_url = os.environ.get("TRIPADVISOR_TERRA_BASE_URL") or DEFAULT_BASE_URL

    body = send_request(base_url, api_key)
    results = body.get("hotels") or body.get("data") or body.get("results") or []
    return [parse_hotel(i + 1, hotel, previous_by_id) for i, hotel in enumerate(results)]


def main() -> None:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    previous_by_id = {h["hotelId"]: h for h in data.get("hotels", [])}

    hotels = fetch_hotels(previous_by_id)
    if not hotels:
        sys.exit("Terra API returned no hotels for Sopron - aborting refresh.")

    data["hotels"] = hotels
    data["sampleStay"] = {
        "checkIn": CHECK_IN,
        "checkOut": CHECK_OUT,
        "nights": NIGHTS,
        "adults": ADULTS,
        "rooms": ROOMS,
    }
    data["generatedAt"] = datetime.now(timezone.utc).isoformat()
    DATA_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Refreshed {len(hotels)} hotels into {DATA_PATH}")


if __name__ == "__main__":
    main()
