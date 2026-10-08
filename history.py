"""Angel historical candles (REST) with a cached login.

Covers what Yahoo never will: NFO/BFO option contracts (plus anything else
by exchange+token). Session re-logs-in automatically when it dies.
"""

import logging
import time
from datetime import datetime

import pyotp
import requests

log = logging.getLogger("broker-bridge")

_INTERVALS = {"ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE", "TEN_MINUTE",
              "FIFTEEN_MINUTE", "THIRTY_MINUTE", "ONE_HOUR", "ONE_DAY"}
_EXCHANGES = {"NSE", "NFO", "BSE", "BFO", "MCX", "CDS"}

_session = {"api": None, "at": 0.0}


def _login(api_key, client_code, password, totp_secret):
    from SmartApi import SmartConnect
    smart = SmartConnect(api_key)
    data = smart.generateSession(client_code, password, pyotp.TOTP(totp_secret).now())
    if not data.get("status"):
        raise RuntimeError(f"angel history login failed: {data}")
    _session.update(api=smart, at=time.time())
    log.info("[history] angel REST login OK")
    return smart


def _api(env):
    if _session["api"] is None or time.time() - _session["at"] > 20 * 3600:
        _login(env["ANGEL_API_KEY"], env["ANGEL_CLIENT_CODE"],
               env["ANGEL_PASSWORD"], env["ANGEL_TOTP_SECRET"])
    return _session["api"]


def candles(env, exchange, token, interval="ONE_MINUTE", frm="", to=""):
    """Returns [{time (unix s), open, high, low, close, volume}]."""
    if exchange not in _EXCHANGES:
        raise ValueError(f"bad exchange {exchange!r}")
    if interval not in _INTERVALS:
        raise ValueError(f"bad interval {interval!r}")
    if not str(token).isdigit():
        raise ValueError(f"bad token {token!r}")
    smart = _api(env)
    try:
        resp = smart.getCandleData({"exchange": exchange, "symboltoken": str(token),
                                    "interval": interval, "fromdate": frm, "todate": to})
    except Exception as e:
        if "401" in str(e) or "token" in str(e).lower() or "session" in str(e).lower():
            _session.update(api=None, at=0.0)
            smart = _api(env)  # one retry on a fresh login
            resp = smart.getCandleData({"exchange": exchange, "symboltoken": str(token),
                                        "interval": interval, "fromdate": frm,
                                        "todate": to})
        else:
            raise
    if not isinstance(resp, dict) or not resp.get("status"):
        raise RuntimeError(f"angel candles rejected: {str(resp)[:200]}")
    out = []
    for row in resp.get("data") or []:
        try:
            ts = datetime.fromisoformat(row[0])
            out.append({"time": int(ts.timestamp()), "open": float(row[1]),
                        "high": float(row[2]), "low": float(row[3]),
                        "close": float(row[4]), "volume": int(float(row[5] or 0))})
        except (ValueError, TypeError, IndexError):
            continue
    return out
