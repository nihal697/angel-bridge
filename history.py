"""Angel historical candles (REST) via the SHARED session.

Covers what Yahoo never will: NFO/BFO option contracts (plus anything else
by exchange+token). NEVER logs in here — see angel_session.
"""

_INTERVALS = {"ONE_MINUTE", "THREE_MINUTE", "FIVE_MINUTE", "TEN_MINUTE",
              "FIFTEEN_MINUTE", "THIRTY_MINUTE", "ONE_HOUR", "ONE_DAY"}
_EXCHANGES = {"NSE", "NFO", "BSE", "BFO", "MCX", "CDS"}

def _api():
    import angel_session
    _jwt, _rest, _feed, smart = angel_session.get_session()
    return smart


def candles(env, exchange, token, interval="ONE_MINUTE", frm="", to=""):
    """Returns [{time (unix s), open, high, low, close, volume}]."""
    if exchange not in _EXCHANGES:
        raise ValueError(f"bad exchange {exchange!r}")
    if interval not in _INTERVALS:
        raise ValueError(f"bad interval {interval!r}")
    if not str(token).isdigit():
        raise ValueError(f"bad token {token!r}")
    smart = _api()
    try:
        resp = smart.getCandleData({"exchange": exchange, "symboltoken": str(token),
                                    "interval": interval, "fromdate": frm, "todate": to})
    except Exception as e:
        if "401" in str(e) or "token" in str(e).lower() or "session" in str(e).lower():
            import angel_session
            angel_session.invalidate()
            smart = _api()  # one retry on a fresh login
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
