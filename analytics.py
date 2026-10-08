"""Pure option analytics: PCR, Max Pain, Black-Scholes IV.

Assumptions (documented, not hidden):
- European exercise (correct for NSE/BSE index options).
- Risk-free r = 6.5% flat; dividends ignored. Small, stated, consistent —
  good enough for paper-trading IV display, not for pricing real trades.
- PCR / Max Pain computed over whatever strikes carry OI (ATM window),
  NOT the full chain — labeled as such wherever shown.
"""

import math

RATE = 0.065


def _ncdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_price(s, k, t_years, r, vol, opt_type):
    """European Black-Scholes price. Returns intrinsic floor on degenerate input."""
    if t_years <= 0 or vol <= 0:
        fwd = s - k * math.exp(-r * max(t_years, 0.0))
        return max(0.0, fwd if opt_type == "CE" else -fwd)
    d1 = (math.log(s / k) + (r + 0.5 * vol * vol) * t_years) / (vol * math.sqrt(t_years))
    d2 = d1 - vol * math.sqrt(t_years)
    disc = math.exp(-r * t_years)
    if opt_type == "CE":
        return s * _ncdf(d1) - k * disc * _ncdf(d2)
    return k * disc * _ncdf(-d2) - s * _ncdf(-d1)


def implied_vol(price, s, k, t_years, opt_type, r=RATE):
    """Bisection IV. None when uninvertible (price at/below intrinsic)."""
    if not (price and price > 0 and s > 0 and k > 0 and t_years > 0):
        return None
    intrinsic = max(s - k, 0.0) if opt_type == "CE" else max(k - s, 0.0)
    if price <= intrinsic:
        return None
    lo, hi = 0.001, 5.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if bs_price(s, k, t_years, r, mid, opt_type) > price:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def put_call_ratio(strikes):
    """Sum PE OI / sum CE OI over strikes that have OI on both sides."""
    ce = sum(r["ce"].get("oi") or 0 for r in strikes)
    pe = sum(r["pe"].get("oi") or 0 for r in strikes)
    if ce <= 0:
        return None
    return pe / ce


def max_pain(strikes):
    """Strike minimizing total writer payout, over strikes with OI data."""
    usable = [r for r in strikes
              if (r["ce"].get("oi") or r["pe"].get("oi"))]
    if not usable:
        return None
    best, best_pain = None, None
    for cand in usable:
        s = cand["strike"]
        pain = 0.0
        for r in usable:
            k = r["strike"]
            pain += max(s - k, 0.0) * (r["ce"].get("oi") or 0)
            pain += max(k - s, 0.0) * (r["pe"].get("oi") or 0)
        if best_pain is None or pain < best_pain:
            best, best_pain = s, pain
    return best


def atm_iv(strikes, spot, expiry_iso, now_iso=None):
    """IV of the ATM call (PE fallback), T from expiry date."""
    if not spot or spot <= 0:
        return None
    try:
        from datetime import date
        exp = date.fromisoformat(expiry_iso)
        today = date.fromisoformat((now_iso or "")[:10]) if now_iso else date.today()
        t = max((exp - today).days, 1) / 365.0
    except (ValueError, TypeError):
        return None
    atm = min((r for r in strikes), key=lambda r: abs(r["strike"] - spot),
              default=None)
    if not atm:
        return None
    for side in ("ce", "pe"):
        leg = atm[side]
        if leg.get("ltp"):
            iv = implied_vol(leg["ltp"], spot, atm["strike"], t,
                             "CE" if side == "ce" else "PE")
            if iv is not None:
                return iv
    return None
