"""Option-chain data from Angel's own instrument master + WS ticks.

No Upstox account needed: the master file lists every NFO/BFO OPTIDX
contract with explicit expiry/strike/lotsize fields, and Angel's websocket
streams their LTPs like any other token.

- Master auto-downloads at startup and refreshes every 24h.
- Combines master structure with live WS ticks; strikes without a tick yet
  report ltp:null instead of a fabricated number.
"""

import json
import logging
import threading
import time
import urllib.request
from datetime import datetime

log = logging.getLogger("broker-bridge")

MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"
MASTER_CACHE = "master_cache.json"  # survives Render sleeps; avoids a 35MB boot download
MASTER_MAX_AGE_DAYS = 7

UNDERLYINGS = {
    # id: (exchange segment, Angel name, WS exchangeType)
    "NIFTY":     ("NFO", "NIFTY", 2),
    "BANKNIFTY": ("NFO", "BANKNIFTY", 2),
    "SENSEX":    ("BFO", "SENSEX", 4),
}

master_rows = []          # filtered OPTIDX rows
master_ts = None          # when the master was loaded
opt_ticks = {}            # token -> {"price": float, "ts": str}
opt_oi = {}               # token -> {"oi": int|None, "ts": str}
_opt_lock = threading.Lock()


def _parse_expiry(s):
    # '29DEC2026' -> date
    try:
        return datetime.strptime(s.strip(), "%d%b%Y").date()
    except (ValueError, AttributeError):
        return None


def _filter_rows(data):
    keep = []
    for row in data:
        try:
            if row.get("instrumenttype") != "OPTIDX":
                continue
            for uid, (seg, name, _et) in UNDERLYINGS.items():
                if row.get("exch_seg") == seg and str(row.get("name")) == name:
                    exp = _parse_expiry(row.get("expiry"))
                    strike = float(str(row.get("strike"))) / 100.0
                    lotsize = int(float(str(row.get("lotsize"))))
                    keep.append({"uid": uid, "token": str(row.get("token")),
                                 "symbol": str(row.get("symbol")),
                                 "expiry": exp.isoformat() if exp else None,
                                 "strike": strike, "lotsize": lotsize,
                                 "type": "CE" if str(row.get("symbol")).endswith("CE") else "PE"})
        except (ValueError, TypeError, AttributeError):
            continue
    return keep


def load_master():
    """Fast disk cache first (survives Render sleeps), then background refresh."""
    global master_rows, master_ts
    import os
    try:
        age_days = (time.time() - os.path.getmtime(MASTER_CACHE)) / 86400
        if age_days < MASTER_MAX_AGE_DAYS:
            with open(MASTER_CACHE, encoding="utf-8") as f:
                master_rows = json.load(f)
            master_ts = datetime.now().isoformat()
            log.info("[chain] master from disk cache: %d rows (%.1fd old)",
                     len(master_rows), age_days)
            return len(master_rows)
    except (OSError, ValueError):
        pass
    return download_master()


def download_master():
    """Full download + keep only the 3 underlyings' OPTIDX rows."""
    global master_rows, master_ts
    log.info("[chain] downloading instrument master (~35MB)…")
    req = urllib.request.Request(MASTER_URL, headers={"User-Agent": "broker-bridge/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    keep = _filter_rows(data)
    del data
    master_rows = keep
    master_ts = datetime.now().isoformat()
    try:
        with open(MASTER_CACHE, "w", encoding="utf-8") as f:
            json.dump(keep, f)
    except OSError as e:
        log.warning("[chain] cache write failed (continuing in-memory): %s", e)
    log.info("[chain] master ready: %d option rows", len(keep))
    return len(keep)


def refresh_loop():
    while True:
        time.sleep(24 * 3600)
        try:
            download_master()
        except Exception as e:
            log.warning("[chain] master refresh failed, keeping old: %s", str(e)[:150])


def expiries(uid):
    return sorted({r["expiry"] for r in master_rows if r["uid"] == uid and r["expiry"]})


def nearest_expiry(uid, today=None):
    today = today or datetime.now().date().isoformat()
    fut = [e for e in expiries(uid) if e >= today]
    return min(fut) if fut else None


def chain_rows(uid, expiry):
    """Master structure for one expiry: {strike: {CE: row, PE: row}}."""
    out = {}
    for r in master_rows:
        if r["uid"] == uid and r["expiry"] == expiry:
            out.setdefault(r["strike"], {})[r["type"]] = r
    return out


def record_tick(token, price, ts):
    with _opt_lock:
        opt_ticks[str(token)] = {"price": price, "ts": ts}


def record_oi(token, oi, ts):
    with _opt_lock:
        opt_oi[str(token)] = {"oi": oi, "ts": ts}

def chain(uid, expiry=None, spot=None):
    """Merge master structure with live ticks + OI; analytics over OI window."""
    from analytics import put_call_ratio, max_pain, atm_iv
    expiry = expiry or nearest_expiry(uid)
    if not expiry:
        return {"underlying": uid, "expiry": None, "spot": spot, "strikes": []}
    rows, lot, newest = [], None, None
    oi_seen = False
    for strike in sorted(chain_rows(uid, expiry)):
        legs = chain_rows(uid, expiry)[strike]
        item = {"strike": strike}
        for side in ("CE", "PE"):
            leg = legs.get(side, {})
            tick = opt_ticks.get(str(leg.get("token", ""))) if leg else None
            oir = opt_oi.get(str(leg.get("token", ""))) if leg else None
            if leg and lot is None:
                lot = leg.get("lotsize", 1)
            cell = {"token": leg.get("token"), "ltp": tick["price"] if tick else None,
                    "ts": tick.get("ts") if tick else None,
                    "oi": (oir or {}).get("oi"),
                    "lot_size": leg.get("lotsize", 1)}
            if tick and tick.get("ts") and (newest is None or tick["ts"] > newest):
                newest = tick["ts"]
            if cell["oi"] is not None:
                oi_seen = True
            item[side.lower()] = cell
        rows.append(item)
    out = {"underlying": uid, "expiry": expiry, "spot": spot,
           "as_of": newest, "lot_size": lot or 1, "strikes": rows,
           "pcr": None, "max_pain": None, "atm_iv": None, "oi_window": oi_seen}
    if oi_seen:
        out["pcr"] = put_call_ratio(rows)
        out["max_pain"] = max_pain(rows)
    if spot:
        out["atm_iv"] = atm_iv(rows, spot, expiry)
    return out
