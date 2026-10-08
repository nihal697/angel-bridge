# broker-bridge (repo: angel-bridge)

Personal multi-broker bridge: live **Nifty 50 / Nifty Bank / Sensex** LTP over
plain HTTP, for personal paper trading. No orders, no redistribution.

- `GET /ltp` → latest ticks (`stale:true` outside 09:15–15:30 IST)
- `GET /health` → broker, socket state, last tick
- `GET /optionchain?underlying=NIFTY&expiry=current_week` → strikes with CE/PE
  LTP, Greeks, OI + lot sizes (Upstox token required; pre-built, needs one
  live test with a real token before the app UI is built on it)
- `GET /optionchain/expiries?underlying=NIFTY` → available expiries
- `GET /history?exchange=NFO&token=44572&interval=ONE_MINUTE&frm=YYYY-MM-DD+HH:MM&to=...`
  → Angel historical candles, incl. option contracts (Yahoo has none for NSE F&O)
Pick the broker with the `BROKER` env var. The `/ltp` shape is identical for
every broker, so the phone app never changes when you switch.

## Broker matrix (honest status)

| BROKER | Auth | Refresh | Cost | Status |
|---|---|---|---|---|
| `angel` | API key + PIN + TOTP, auto re-login | automatic | free (clients) | ✅ proven against the live API |
| `dhan` | static API token, never expires | never | free (clients) | built from v2 docs + live instrument master |
| `shoonya` | UID + password + PAN/DOB + vendor code, auto re-login | automatic | free (clients) | built from the lib source itself |
| `fyers` | browser-issued token, ~daily | manual, in FYERS portal | free (clients) | built from official samples |
| `upstox` | OAuth token, ~daily | manual, in developer portal | free (clients) | built from v2 docs |
| `zerodha` | API key + daily token | manual, daily | **~Rs 2,000/mo** | built from live instrument dump |

Only `angel` has done a live login test from here. The rest are
docs-verified and import-tested — each needs one live run with your keys
before you trust it (the logs say plainly what's wrong if not).

Index references used (all read from live masters/dumps, not memory):
Angel NSE 99926000/99926009, BSE 99919000 · Dhan IDX_I 13/25/51 ·
Shoonya NSE 26000/26009, BSE 1 · FYERS NSE:NIFTY50-INDEX, NSE:NIFTYBANK-INDEX,
BSE:SENSEX-INDEX · Upstox NSE_INDEX|Nifty 50, NSE_INDEX|Nifty Bank,
BSE_INDEX|SENSEX · Kite NSE 256265/260105, BSE 265.

## Deploy on Render (free)

New → Blueprint → this repo (or Web Service with the commands in
`render.yaml`). Set `BROKER` plus only that broker's env vars (see
`render.yaml` for names). Deploy, then open `/health`.

- Render free sleeps after ~15 min idle — a free UptimeRobot ping every
  14 min on weekdays keeps it warm.
- Personal use only: exchange rules forbid republishing broker data feeds.

## Use it

```bash
curl https://<your-app>.onrender.com/ltp
# {"market_open": true, "stale": false, "broker": "dhan",
#  "data": {"NIFTY": {"price": 26178.4, "ts": "..."}, ...}}
```
