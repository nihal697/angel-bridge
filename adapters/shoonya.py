"""Shoonya/Finvasia (Noren) adapter (REST polling). Status: BUILT FROM LIB SOURCE.

Login + quote shapes taken from the NorenRestApiPy source itself (not memory):
login() hashes password itself (sha256) and derives appkey as
sha256("userid|api_secret") — env values go in PLAIN, hashing happens here.
Session re-logs-in automatically whenever quotes stop authenticating.
Env: SHOONYA_UID, SHOONYA_PASSWORD (plain), SHOONYA_FACTOR2 (PAN or DOB
DD-MM-YYYY), SHOONYA_VENDOR_CODE, SHOONYA_API_SECRET. Optional SHOONYA_IMEI.
Index tokens are the standard NSE/BSE codes (NSE 26000/26009, BSE 1).
"""

import hashlib
import json
import logging
import os

import requests

from .base import env, poll_forever

log = logging.getLogger("broker-bridge")

NAME = "shoonya"
REQUIRED_ENV = ["SHOONYA_UID", "SHOONYA_PASSWORD", "SHOONYA_FACTOR2",
                "SHOONYA_VENDOR_CODE", "SHOONYA_API_SECRET"]

BASE = "https://api.shoonya.com/NorenWClientTP"
QUOTES = [("NSE", "26000", "NIFTY"), ("NSE", "26009", "BANKNIFTY"), ("BSE", "1", "SENSEX")]

_session = {"uid": None, "token": None}


def _login():
    uid = env("SHOONYA_UID")
    pwd = hashlib.sha256(env("SHOONYA_PASSWORD").encode()).hexdigest()
    appkey = hashlib.sha256(f"{uid}|{env('SHOONYA_API_SECRET')}".encode()).hexdigest()
    values = {"source": "API", "apkversion": "1.0.0", "uid": uid, "pwd": pwd,
              "factor2": env("SHOONYA_FACTOR2"), "vc": env("SHOONYA_VENDOR_CODE"),
              "appkey": appkey, "imei": os.environ.get("SHOONYA_IMEI", "brokerbridge")}
    r = requests.post(f"{BASE}/QuickAuth", data="jData=" + json.dumps(values), timeout=15)
    d = r.json()
    if d.get("stat") != "Ok":
        raise RuntimeError(f"shoonya login failed: {d.get('emsg', d)}")
    _session.update(uid=uid, token=d["susertoken"])
    log.info("[shoonya] login OK")


def _quote(exch, token):
    r = requests.post(
        f"{BASE}/GetQuotes",
        data="jData=" + json.dumps({"uid": _session["uid"], "exch": exch, "token": token})
             + f"&jKey={_session['token']}",
        timeout=10,
    )
    return r.json()


def fetch_all():
    if not _session["token"]:
        _login()
    out = {}
    for exch, token, sid in QUOTES:
        d = _quote(exch, token)
        if d.get("stat") != "Ok":
            if "Session" in str(d.get("emsg", "")):
                _session["token"] = None  # force re-login next round
                raise RuntimeError(f"session expired: {d.get('emsg')}")
            log.warning("[shoonya] quote miss %s %s: keys=%s", exch, token, list(d.keys()))
            continue
        for key in ("lp", "ltp", "last_price", "lastPrice"):
            if d.get(key) is not None:
                out[sid] = float(d[key])
                break
    return out


def run_forever(on_tick):
    log.info("[shoonya] polling quotes (auto re-login on expiry)")
    poll_forever(NAME, fetch_all, on_tick)
