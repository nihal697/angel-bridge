"""Angel REST FULL quotes (documented shape) — the OI source.

POST /rest/secure/angelbroking/market/v1/quote/ with
{"mode": "FULL", "exchangeTokens": {"NFO": [...], "BSE": [...]}}.
50 tokens per call, ~1 call/sec: our ~50 option tokens fit in ONE call,
polled every 60s (OI barely moves faster than that).
Auth: same JWT login as everything else; re-logs-in on rejection.
"""

import logging
import time

import pyotp
import requests

log = logging.getLogger("broker-bridge")

URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote/"
HEADERS = {"Accept": "application/json", "Content-Type": "application/json",
           "X-SourceID": "WEB", "X-UserType": "USER",
           "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
           "X-MACAddress": "00:00:00:00:00:00"}

_session = {"jwt": None, "at": 0.0}


def _login(env):
    from SmartApi import SmartConnect
    smart = SmartConnect(env["ANGEL_API_KEY"])
    data = smart.generateSession(env["ANGEL_CLIENT_CODE"], env["ANGEL_PASSWORD"],
                                 pyotp.TOTP(env["ANGEL_TOTP_SECRET"]).now())
    if not data.get("status"):
        raise RuntimeError(f"angel OI login failed: {data}")
    # The market REST API only accepts the token minted by generateToken —
    # the raw login jwt gets AG8001 Invalid Token. (Proven live.)
    gt = smart.generateToken(data["data"]["refreshToken"])
    if not gt.get("status"):
        raise RuntimeError(f"angel OI token mint failed: {gt}")
    _session.update(jwt=gt["data"]["jwtToken"], at=time.time())
    log.info("[oi] angel REST login OK")
    return gt["data"]["jwtToken"]


def _jwt(env):
    if not _session["jwt"] or time.time() - _session["at"] > 20 * 3600:
        return _login(env)
    return _session["jwt"]


def fetch_oi(env, tokens_by_exch):
    """{(exchange, token): {oi, ltp}} — empty dict on any failure (never throws)."""
    tokens_by_exch = {k: [str(t) for t in v if t] for k, v in tokens_by_exch.items() if v}
    if not tokens_by_exch:
        return {}
    try:
        jwt = _jwt(env)
    except Exception as e:
        log.warning("[oi] login failed: %s", str(e)[:150])
        return {}
    headers = dict(HEADERS, Authorization=f"Bearer {jwt}", **{"X-PrivateKey": env["ANGEL_API_KEY"]})
    try:
        r = requests.post(URL, headers=headers,
                          json={"mode": "FULL", "exchangeTokens": tokens_by_exch}, timeout=20)
    except Exception as e:
        log.warning("[oi] request failed: %s", str(e)[:150])
        return {}
    if r.status_code == 401:
        _session.update(jwt=None, at=0.0)
        log.warning("[oi] token rejected, will re-login next round")
        return {}
    try:
        body = r.json()
    except ValueError:
        log.warning("[oi] non-JSON response: %s", r.text[:120])
        return {}
    if not body.get("status"):
        log.warning("[oi] rejected: %s", str(body)[:200])
        return {}
    out = {}
    for row in body.get("data", {}).get("fetched", []) or []:
        tok = str(row.get("symbolToken", ""))
        oi = row.get("opnInterest")
        try:
            oi_val = int(float(oi)) if oi is not None else None
        except (TypeError, ValueError):
            oi_val = None
        out[(row.get("exchange"), tok)] = {"oi": oi_val, "ltp": row.get("ltp")}
    return out
