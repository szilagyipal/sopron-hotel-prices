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
| `TRIPADVISOR_API_KEY` | yes | Your Tripadvisor Terra API key |
| `TRIPADVISOR_TERRA_BASE_URL` | yes | Terra API base URL for your account - see [docs.terra.tripadvisor.com](https://docs.terra.tripadvisor.com/docs/overview) or your account dashboard |
| `TRIPADVISOR_AUTH_STYLE` | no | `bearer` (default) or `header` - see `refresh.py` |

Until both required secrets are set, the scheduled workflow will fail
without changing `data.json`, so the live widget just keeps showing the
last good snapshot.

You can trigger a refresh immediately (rather than waiting for the daily
schedule) from the Actions tab → "Refresh Sopron hotel prices" → "Run
workflow".
