# sopron-hotel-prices

Daily-refreshed Tripadvisor hotel ranking/price feed for Sopron, Hungary.

`data.json` is fetched client-side (via `raw.githubusercontent.com`, which
serves CORS-enabled responses) by the hotel showcase widget embedded on
[bestofsopron.eu](https://bestofsopron.eu/index.php/szallodak). The
widget's own code lives in the `sopron_hotels/` folder of the
[`firstofall`](https://github.com/szilagyipal/firstofall) repo; this repo
exists only to host the data feed publicly so that widget can auto-update
without anyone re-pasting anything into the CMS.

## How it updates

`.github/workflows/refresh.yml` runs `refresh.py` once a day (02:00 UTC,
i.e. ~3am CET) via GitHub Actions, and commits `data.json` if it changed.
It never touches `data.json` on a failed run, so a bad API response can't
wipe out the live feed.

## One-time setup required

`refresh.py` needs these as **repository secrets** (Settings → Secrets and
variables → Actions → New repository secret) - never commit them to a file:

| Secret | Required | Notes |
|---|---|---|
| `TRIPADVISOR_API_KEY` | yes | Your Tripadvisor Terra/Partner API key |
| `TRIPADVISOR_TERRA_BASE_URL` | no | Defaults to `https://terra.tripadvisor.com/api`. Only set this if your account uses a different host. |
| `TRIPADVISOR_AUTH_MODE` | no | `header` (default, `X-API-Key: <key>`) or `query` (`?key=<key>`) - escape hatch only, header is confirmed working |

Until `TRIPADVISOR_API_KEY` is set, the scheduled workflow will fail
without changing `data.json`, so the live widget just keeps showing the
last good snapshot.

**Confirmed working:** base URL, the `X-API-Key` header, and the
`POST /recommendations/search` request shape (`{"query": ..., "geo":
{"name": ...}, "limit": ..., "response_preference": "quality"}`). The
first few real runs hit a `403 Forbidden` ("API Key does not have access
to endpoint") because Sopron's Tripadvisor geo ID (`274909`) wasn't on
this key's allowlist (`GET /allowlist` came back empty) - `refresh.py`
now self-heals that automatically by `POST`ing `{"allowlist": [274909],
"operation_type": "APPEND"}` (additive only) and retrying the search
once, so this should no longer need manual intervention.

**Still open:** the exact shape of a successful `/recommendations/search`
response for hotels is unconfirmed - `refresh.py` logs the full response
body on success, so check the latest run's log and adjust `parse_hotel()`
if the field names it reads (`hotelId`/`location_id`, `hotelName`/`name`,
`reviewSummary`, `priceInfo`, etc.) don't match what actually comes back.
Pricing in particular was never listed among the Partner API's documented
data types (Location/Reviews/Photos/Geo/Recommendations only), so it may
not be present at all - `parse_hotel()` keeps each hotel's last known
price rather than zeroing it out if a response has none.

You can trigger a refresh immediately (rather than waiting for the daily
schedule) from the Actions tab → "Refresh Sopron hotel prices" → "Run
workflow".
