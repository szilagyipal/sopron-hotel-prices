#!/usr/bin/env python3
"""Refreshes data.json with current Sopron hotel rankings/prices from the
Tripadvisor Terra API (https://docs.terra.tripadvisor.com/docs/overview).

Run by the "Refresh Sopron hotel prices" GitHub Actions workflow daily.
data.json is fetched by the hotel showcase widget on bestofsopron.eu via
raw.githubusercontent.com - this script is the only thing that writes it.

Required environment variables:
    TRIPADVISOR_API_KEY         Your Terra API key.
    TRIPADVISOR_TERRA_BASE_URL  The Terra API base URL for your account -
                                 see the docs above / your account dashboard.
                                 This script does not guess it.

Optional environment variables:
    TRIPADVISOR_AUTH_STYLE  "bearer" (default, sends
                             "Authorization: Bearer <key>") or "header"
                             (sends the raw key in an "X-Tripadvisor-Api-Key"
                             header instead). Adjust send_request() below if
                             your account uses a different scheme entirely.
    SOPRON_LOCATION          Defaults to "Sopron, Hungary".
    SOPRON_CHECK_IN          YYYY-MM-DD, defaults to 14 days from today.
    SOPRON_NIGHTS            Defaults to 1.

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


def parse_hotel(rank: int, hotel: dict) -> dict:
    price_info = hotel.get("priceInfo") or {}
    review = hotel.get("reviewSummary") or {}
    styles = [
        s["styleName"]
        for s in hotel.get("locationV2", {}).get("hotelStyleRankings", [])
    ]

    def _to_amount(value: str) -> float:
        return float(value.replace("$", "").replace(",", "")) if value else 0.0

    return {
        "rank": rank,
        "hotelId": hotel.get("hotelId"),
        "name": hotel.get("hotelName", "Unknown Hotel"),
        "rating": review.get("rating", 0),
        "reviewCount": review.get("count", 0),
        "priceFrom": _to_amount(price_info.get("displayPrice", "")),
        "taxesAndFees": _to_amount(price_info.get("displayTaxesAndFees", "")),
        "styles": styles[:3],
        "thumbnail": _thumbnail_url(hotel),
        "tripadvisorUrl": _tripadvisor_url(hotel),
    }


def send_request(base_url: str, api_key: str) -> dict:
    auth_style = os.environ.get("TRIPADVISOR_AUTH_STYLE", "bearer").lower()
    headers = {"Content-Type": "application/json"}
    if auth_style == "header":
        headers["X-Tripadvisor-Api-Key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"

    response = requests.post(
        f"{base_url.rstrip('/')}/hotels/search",
        headers=headers,
        json={
            "location": LOCATION,
            "checkIn": CHECK_IN,
            "checkOut": CHECK_OUT,
            "guests": ADULTS,
            "rooms": ROOMS,
            "sortBy": "POPULARITY",
            "limit": 20,
            "pricingMode": "QUICK",
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch_hotels() -> list:
    api_key = os.environ.get("TRIPADVISOR_API_KEY")
    base_url = os.environ.get("TRIPADVISOR_TERRA_BASE_URL")
    if not api_key or not base_url:
        sys.exit(
            "Set TRIPADVISOR_API_KEY and TRIPADVISOR_TERRA_BASE_URL "
            "(see docs.terra.tripadvisor.com/docs/overview for your "
            "account's base URL and auth header) before running this script."
        )

    body = send_request(base_url, api_key)
    return [
        parse_hotel(i + 1, hotel) for i, hotel in enumerate(body.get("hotels", []))
    ]


def main() -> None:
    hotels = fetch_hotels()
    if not hotels:
        sys.exit("Terra API returned no hotels for Sopron - aborting refresh.")

    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
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
