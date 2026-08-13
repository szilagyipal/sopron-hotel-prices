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
| `TRIPADVISOR_AUTH_MODE` | no | Pin to one auth scheme instead of trying all of them each run - see `refresh.py`'s `_auth_candidates()` for the exact values |

Until `TRIPADVISOR_API_KEY` is set, the scheduled workflow will fail
without changing `data.json`, so the live widget just keeps showing the
last good snapshot.

**Status as of the first real run:** `https://terra.tripadvisor.com/api`
is reachable and `POST /recommendations/search` exists (confirmed by a
clean `401`, not a connection error), but the `X-Tripadvisor-API-Key`
header scheme was rejected. `refresh.py` now tries several plausible auth
schemes per run and logs which one (if any) gets past authentication -
check the latest run's log for a line like `Auth scheme '...' got past
authentication`. If all of them 401, the key itself likely needs
checking on the Terra dashboard (inactive, wrong product/plan, etc.)
rather than the scheme being wrong.

**Known gap:** Tripadvisor's published Partner API endpoint overview
(`/recommendations/search`, `/locations/{id}`, `/locations/{id}/reviews`,
`/locations/{id}/photos`, `/geos/{id}`, plus feed/allowlist endpoints)
doesn't list pricing among its data types - live per-night pricing is
usually a separate sponsored-placement feed. Until that's confirmed one
way or the other, `refresh.py` updates rank/rating/review data normally
each run but keeps a hotel's last known price if the response doesn't
include one, rather than zeroing it out.

You can trigger a refresh immediately (rather than waiting for the daily
schedule) from the Actions tab → "Refresh Sopron hotel prices" → "Run
workflow".
