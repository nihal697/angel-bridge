# angel-bridge

Personal Angel One SmartAPI bridge: live **Nifty 50 / Nifty Bank / Sensex** LTP
over plain HTTP, for personal paper trading. No orders, no redistribution.

- `GET /ltp` → latest ticks (`stale:true` outside 09:15–15:30 IST)
- `GET /health` → socket state, last login, last tick

## 1. Angel side (5 min, free for Angel One clients)

1. Log in at [smartapi.angelone.in](https://smartapi.angelone.in) → **My APIs / Create App** → copy the **API key**.
2. On the same portal, find the **TOTP secret / QR value** for your app and save the text secret (this is what lets code log in without your phone).
3. You need: API key, client code, PIN/password, TOTP secret.

## 2. Deploy on Render (free)

1. Push this repo (or fork it), then **New → Web Service → this repo** on Render
   (or use `render.yaml` — Blueprint).
2. Add 4 environment variables (never commit these):
   `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PASSWORD`, `ANGEL_TOTP_SECRET`.
3. Deploy. Open `https://<your-app>.onrender.com/health` — `connected:true`
   during market hours means live ticks are flowing.

Notes:

- Angel sessions expire ~daily; the bridge re-logs-in and reconnects on its own.
- Render free sleeps after ~15 min idle — first load of the day is slow, then
  polling keeps it warm. A free UptimeRobot ping every 14 min on weekdays
  fixes even that.
- Personal use only: exchange rules forbid republishing broker data feeds.

## 3. Use it

```bash
curl https://<your-app>.onrender.com/ltp
# {"market_open": true, "stale": false,
#  "data": {"NIFTY": {"price": 26178.4, "ts": "..."}, ...}}
```

Next step (not done here): point the DailyTrade fork at this endpoint as an
"Angel live" source next to Yahoo.
