#!/usr/bin/env python3
"""Refreshes data.json with current Sopron hotel rankings/prices from the
Tripadvisor Terra API (https://docs.terra.tripadvisor.com/docs/overview).

Run by the "Refresh Sopron hotel prices" GitHub Actions workflow daily.
data.json is fetched by the hotel showcase widget on bestofsopron.eu via
raw.githubusercontent.com - this script is the only thing that writes it.

Per Tripadvisor's Partner API overview, every endpoint requires an
"X-API-KEY" header, and hotel search is POST /recommendations/search.
That overview does NOT list pricing as one of the API's data types
(Location/Reviews/Photos/Geo/Recommendations only) - Tripadvisor's live
per-night pricing is typically a separate sponsored-placement feed, not
part of the general Partner API. Until that's confirmed one way or the
other, parse_hotel() below keeps each hotel's previous price rather than
zeroing it out if the response has no price field, and rank/rating/review
data updates normally.

Required environment variables:
    TRIPADVISOR_API_KEY         Your Terra/Partner API key.
    TRIPADVISOR_TERRA_BASE_URL  The Terra API base host for your account,
                                 e.g. "https://api.某.tripadvisor.com" -
                                 not in the endpoint overview, so this
                                 script does not guess it.

Optional environment variables:
    SOPRON_LOCATION   Defaults to "Sopron, Hungary".
    SOPRON_CHECK_IN   YYYY-MM-DD, defaults to 14 days from today.
    SOPRON_NIGHTS     Defaults to 1.

TODO once the /recommendations/search request/response schema is
confirmed (the endpoint overview only lists the path, not its body):
verify the request payload below and the field names parse_hotel() reads
match a real response.

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


def send_request(base_url: str, api_key: str) -> dict:
    headers = {
        "X-API-KEY": api_key,
        "Content-Type": "application/json",
    }

    response = requests.post(
        f"{base_url.rstrip('/')}/recommendations/search",
        headers=headers,
        json={
            "location": LOCATION,
            "checkIn": CHECK_IN,
            "checkOut": CHECK_OUT,
            "guests": ADULTS,
            "rooms": ROOMS,
            "sortBy": "POPULARITY",
            "limit": 20,
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch_hotels(previous_by_id: dict) -> list:
    api_key = os.environ.get("TRIPADVISOR_API_KEY")
    base_url = os.environ.get("TRIPADVISOR_TERRA_BASE_URL")
    if not api_key or not base_url:
        sys.exit(
            "Set TRIPADVISOR_API_KEY and TRIPADVISOR_TERRA_BASE_URL "
            "(see docs.terra.tripadvisor.com/docs/overview for your "
            "account's base URL) before running this script."
        )

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
