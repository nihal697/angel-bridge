"""ONE Angel session shared by everything (WS + REST + history).

Angel kills older sessions when a new login lands. Separate logins for the
WS loop, the OI poller and history therefore murder each other in turn —
each death looks like "connected with fresh timestamps but stale values".
All Angel traffic in this process goes through get_session() under one lock.
"""

import logging
import threading
import time

import pyotp

log = logging.getLogger("broker-bridge")

_lock = threading.Lock()
_sess = {"jwt": None, "rest_jwt": None, "feed": None, "smart": None, "at": 0.0}
TTL = 20 * 3600


def _read_env():
    import os
    return {k: os.environ[k] for k in
            ("ANGEL_API_KEY", "ANGEL_CLIENT_CODE", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET")}


def get_session():
    """(login_jwt, rest_jwt, feed_token, SmartConnect). One login, shared.

    WS keeps the login jwt (proven live); REST uses the minted one
    (login jwt gets AG8001 there — proven live).
    """
    with _lock:
        if _sess["jwt"] and time.time() - _sess["at"] < TTL:
            return _sess["jwt"], _sess["rest_jwt"], _sess["feed"], _sess["smart"]
        from SmartApi import SmartConnect
        env = _read_env()  # KeyError names the missing var plainly
        smart = SmartConnect(env["ANGEL_API_KEY"])
        data = smart.generateSession(env["ANGEL_CLIENT_CODE"], env["ANGEL_PASSWORD"],
                                     pyotp.TOTP(env["ANGEL_TOTP_SECRET"]).now())
        if not data.get("status"):
            raise RuntimeError(f"angel login failed: {data}")
        rest_jwt = data["data"]["jwtToken"]
        try:
            gt = smart.generateToken(data["data"]["refreshToken"])
            if gt.get("status"):
                rest_jwt = gt["data"]["jwtToken"]
        except Exception as e:
            log.warning("[session] token mint failed, REST falls back to login jwt: %s",
                        str(e)[:120])
        feed = smart.getfeedToken()
        _sess.update(jwt=data["data"]["jwtToken"], rest_jwt=rest_jwt,
                     feed=feed, smart=smart, at=time.time())
        log.info("[session] angel login OK (shared)")
        return _sess["jwt"], _sess["rest_jwt"], _sess["feed"], _sess["smart"]


def invalidate():
    with _lock:
        _sess.update(jwt=None, rest_jwt=None, feed=None, smart=None, at=0.0)
