#!/usr/bin/env python3
"""Refreshes data.json with current Sopron hotel rankings/prices from the
Tripadvisor Terra API (https://docs.terra.tripadvisor.com/docs/overview).

Run by the "Refresh Sopron hotel prices" GitHub Actions workflow daily.
data.json is fetched by the hotel showcase widget on bestofsopron.eu via
raw.githubusercontent.com - this script is the only thing that writes it.

Base URL: https://terra.tripadvisor.com/api (confirmed reachable).
Auth: "X-API-Key: <key>" header - confirmed (run #4: other schemes got a
clean 401 "API key is not provided" on the same request, X-API-Key alone
got a 403, proving it's the one actually being read as a credential).
Request shape for POST /recommendations/search - confirmed from
Tripadvisor's readme.io reference: {"query": <natural language>, "geo":
{"name": <place>}, "limit": <n>, "response_preference": "quality"}. This
is a semantic recommendations endpoint, not a structured price-search
API - there's no date/guest/room/sort field in the schema at all, which
lines up with pricing never appearing among the Partner API's documented
data types (Location/Reviews/Photos/Geo/Recommendations only). Until
that's confirmed one way or the other, parse_hotel() below keeps each
hotel's previous price rather than zeroing it out if a response has none.

That 403 turned out to be an allowlist gap, not an auth or payload
problem: GET /allowlist came back 200 with zero entries, and the 403 body
said "API Key does not have access to endpoint". Per Tripadvisor's
POST /allowlist reference (also confirmed by the repo owner), the fix is
appending this account's queryable location IDs - so send_request() now
auto-heals a 403 by POSTing {"allowlist": [SOPRON_GEO_ID],
"operation_type": "APPEND"} (additive only, never removes/replaces
existing entries) and retrying the search once.

Required environment variable:
    TRIPADVISOR_API_KEY  Your Terra/Partner API key.

Optional environment variables:
    TRIPADVISOR_TERRA_BASE_URL  Overrides the default base URL above.
    TRIPADVISOR_AUTH_MODE        "header" (default) or "query" (sends the
                                  key as ?key=... instead, in case the
                                  header scheme ever stops working).
    SOPRON_LOCATION               Defaults to "Sopron, Hungary".
    SOPRON_CHECK_IN                YYYY-MM-DD, defaults to 14 days from today.
    SOPRON_NIGHTS                  Defaults to 1.

TODO once a run returns real hotel data: check the logged full response
body against parse_hotel()'s field names and adjust if they don't match -
the exact response shape for this endpoint is still unconfirmed.

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
# Tripadvisor's own geo ID for Sopron, Hungary - confirmed live via the
# Terra hotel-search tool ("searchGeoData":{"geoId":274909,"name":"Sopron"}).
SOPRON_GEO_ID = 274909

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


def _auth_kwargs(api_key: str) -> dict:
    """requests() kwargs for the confirmed auth scheme. TRIPADVISOR_AUTH_MODE
    is an escape hatch (query param instead of header) in case the header
    scheme ever stops working - not needed under normal operation."""
    if os.environ.get("TRIPADVISOR_AUTH_MODE", "").strip().lower() == "query":
        return {"headers": {"Content-Type": "application/json"}, "params": {"key": api_key}}
    return {"headers": {"Content-Type": "application/json", "X-API-Key": api_key}, "params": None}


def _upload_allowlist(base_url: str, auth_kwargs: dict) -> bool:
    """POST {"allowlist": [SOPRON_GEO_ID], "operation_type": "APPEND"} to
    /allowlist. APPEND only adds to the existing allowlist - it never
    removes or replaces entries. Returns whether the call succeeded."""
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/allowlist",
            json={"allowlist": [SOPRON_GEO_ID], "operation_type": "APPEND"},
            timeout=15,
            **auth_kwargs,
        )
        print(f"POST /allowlist (APPEND [{SOPRON_GEO_ID}]): {resp.status_code} {resp.text[:1000]}")
        return resp.ok
    except requests.RequestException as exc:
        print(f"POST /allowlist failed: {exc}")
        return False


def send_request(base_url: str, api_key: str) -> dict:
    url = f"{base_url.rstrip('/')}/recommendations/search"
    payload = {
        "query": f"best hotels in {LOCATION}",
        "geo": {"name": LOCATION},
        "limit": 20,
        "response_preference": "quality",
    }
    auth_kwargs = _auth_kwargs(api_key)

    response = requests.post(url, json=payload, timeout=30, **auth_kwargs)

    if response.status_code == 403:
        # Confirmed via run #5: this means the key IS valid but Sopron
        # isn't allowlisted yet, not a wrong auth scheme or payload - see
        # the module docstring. Self-heal once, then retry the search.
        print(f"Search denied (403), attempting to allowlist Sopron (geo id {SOPRON_GEO_ID}): {response.text[:500]}")
        if not _upload_allowlist(base_url, auth_kwargs):
            sys.exit("Allowlist upload failed - see the POST /allowlist response above.")
        response = requests.post(url, json=payload, timeout=30, **auth_kwargs)

    if not response.ok:
        print(f"Response body: {response.text[:2000]}")
    response.raise_for_status()
    body = response.json()
    print(f"Response JSON keys: {list(body.keys())}")
    # Full dump so response parsing can be nailed down from this run's log
    # alone, without yet another manual dispatch round trip.
    print(f"Full response body:\n{json.dumps(body, indent=2)[:4000]}")
    return body


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
