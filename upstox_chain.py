"""Upstox option-chain provider (REST, documented shapes only).

Endpoints used (per Upstox v2 developer docs):
  GET /v2/option/chain?instrument_key=...&expiry_date=...
      -> {data: [{strike_price, underlying_spot_price,
                  call_options: {instrument_key, market_data: {ltp,...},
                                 option_greeks: {delta,theta,gamma,vega,iv}},
                  put_options: {...}}]}
  GET /v2/option/contract?instrument_key=...  -> lot sizes per contract.

Auth: Bearer UPSTOX_ACCESS_TOKEN (daily OAuth token). No token caching
tricks here — a 401 surfaces as a plain-language error, never a traceback.
"""

import logging
from datetime import date

import requests

from adapters.base import env

log = logging.getLogger("broker-bridge")

UNDERLYINGS = {
    "NIFTY":     "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "SENSEX":    "BSE_INDEX|SENSEX",
}
BASE = "https://api.upstox.com/v2"

_lots_cache = {}  # (underlying) -> {instrument_key: lot_size}


class UpstoxAuthError(RuntimeError):
    pass


def _headers():
    return {"Authorization": f"Bearer {env('UPSTOX_ACCESS_TOKEN')}",
            "Accept": "application/json"}


def _get(path, params):
    r = requests.get(f"{BASE}{path}", headers=_headers(), params=params, timeout=15)
    if r.status_code == 401:
        raise UpstoxAuthError("upstox token rejected (401) — refresh it in the developer portal")
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        raise RuntimeError(f"upstox rejected the call: {str(body)[:200]}")
    return body.get("data", [])


def _lots(underlying):
    """instrument_key -> lot_size, cached per process (lots don't change intraday)."""
    if underlying not in _lots_cache:
        rows = _get("/option/contract", {"instrument_key": UNDERLYINGS[underlying]})
        _lots_cache[underlying] = {row.get("instrument_key"): row.get("lot_size", 1)
                                    for row in rows if row.get("instrument_key")}
    return _lots_cache[underlying]


def _side(node):
    md = (node or {}).get("market_data", {}) or {}
    gk = (node or {}).get("option_greeks", {}) or {}
    ltp = md.get("ltp")
    return {
        "ltp": float(ltp) if ltp is not None else None,
        "volume": md.get("volume"), "oi": md.get("oi"),
        "bid": md.get("bid_price"), "ask": md.get("ask_price"),
        "iv": gk.get("iv"), "delta": gk.get("delta"), "theta": gk.get("theta"),
        "gamma": gk.get("gamma"), "vega": gk.get("vega"),
    }


def expiries(underlying):
    rows = _get("/option/contract", {"instrument_key": UNDERLYINGS[underlying]})
    return sorted({r["expiry"] for r in rows if r.get("expiry")})


def chain(underlying, expiry="current_week"):
    rows = _get("/option/chain", {"instrument_key": UNDERLYINGS[underlying],
                                  "expiry_date": expiry})
    lots = _lots(underlying)
    out, spot = [], None
    for r in rows:
        spot = r.get("underlying_spot_price", spot)
        ce, pe = r.get("call_options", {}), r.get("put_options", {})
        out.append({
            "strike": r.get("strike_price"),
            "expiry": r.get("expiry"),
            "lot_size": lots.get(ce.get("instrument_key")) or lots.get(pe.get("instrument_key")) or 1,
            "ce": _side(ce), "pe": _side(pe),
        })
    return {"underlying": underlying, "expiry": expiry,
            "spot": spot, "strikes": out}
