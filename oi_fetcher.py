"""Angel REST FULL quotes (documented shape) — the OI source.

Uses the SHARED session (angel_session). NEVER logs in here: a second
concurrent login kills the WS session server-side (proven the hard way).
Tokens are chunked to <=50 per call (AB4029 above that), ~1.2s apart.

POST /rest/secure/angelbroking/market/v1/quote/ with
{"mode": "FULL", "exchangeTokens": {"NFO": [...], "BSE": [...]}},
polled every 60s (OI barely moves faster than that).
"""

import logging
import time

import requests

log = logging.getLogger("broker-bridge")

URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote/"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json",
           "X-SourceID": "WEB", "X-UserType": "USER",
           "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
           "X-MACAddress": "00:00:00:00:00:00"}

def _jwt():
    import angel_session
    _login_jwt, rest_jwt, _feed, _smart = angel_session.get_session()
    return rest_jwt


def fetch_oi(env, tokens_by_exch):
    """{(exchange, token): {oi, ltp}} — empty dict on any failure (never throws)."""
    tokens_by_exch = {k: [str(t) for t in v if t] for k, v in tokens_by_exch.items() if v}
    if not tokens_by_exch:
        return {}
    try:
        jwt = _jwt()
    except Exception as e:
        log.warning("[oi] session failed: %s", str(e)[:150])
        return {}
    import os
    headers = dict(HEADERS, Authorization=f"Bearer {jwt}", **{"X-PrivateKey": os.environ["ANGEL_API_KEY"]})
    out = {}
    fetched = []
    chunks = []
    for exch, toks in tokens_by_exch.items():
        for i in range(0, len(toks), 50):
            chunks.append({exch: toks[i:i + 50]})
    for chunk in chunks:
        try:
            r = requests.post(URL, headers=headers,
                              json={"mode": "FULL", "exchangeTokens": chunk}, timeout=20)
        except Exception as e:
            log.warning("[oi] request failed: %s", str(e)[:150])
            return out
        if r.status_code == 401:
            import angel_session
            angel_session.invalidate()
            log.warning("[oi] token rejected, session invalidated")
            return out
        try:
            body = r.json()
        except ValueError:
            log.warning("[oi] non-JSON response: %s", r.text[:120])
            return out
        if not body.get("status"):
            log.warning("[oi] rejected: %s", str(body)[:200])
            return out
        fetched.extend(body.get("data", {}).get("fetched", []) or [])
        time.sleep(1.2)  # documented ~1 call/sec
    for row in fetched:
        tok = str(row.get("symbolToken", ""))
        oi = row.get("opnInterest")
        try:
            oi_val = int(float(oi)) if oi is not None else None
        except (TypeError, ValueError):
            oi_val = None
        out[(row.get("exchange"), tok)] = {"oi": oi_val, "ltp": row.get("ltp")}
    return out
