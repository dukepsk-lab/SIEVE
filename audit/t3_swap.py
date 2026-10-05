"""Task 3: swap and financing.

MT5 stores swap_long / swap_short; their unit depends on swap_mode:
  POINTS            money/night = lots x swap x point x (tick_value/tick_size)       -> index points/night = swap x point
  CURRENCY_SYMBOL   money in the symbol's base currency per lot per night             -> pts = swap / (tick_value/tick_size)   (USD profit ccy)
  CURRENCY_DEPOSIT  money in the account currency per lot per night                   -> pts = swap / (tick_value/tick_size)
  CURRENCY_MARGIN   money in the margin currency per lot per night                    -> same conversion (USD margin ccy)
  INTEREST_*        swap is an annual percentage of notional                          -> pts = price x swap/100 / 365
  REOPEN_*          position is reopened at the current/bid price at rollover: swap in points, same as POINTS
  DISABLED          the terminal states that no swap is charged
Negative = paid by the trader. The triple-swap weekday is swap_rollover3days (0=Sunday .. 6=Saturday).
"""
import pandas as pd

from .t0_preflight import DAYS, SWAP_MODES


def run(spec: dict, price: float, deals: dict, landscape: pd.DataFrame) -> dict:
    mode, pt = spec["swap_mode"], spec["point"]
    usd_per_idx_pt = spec["_units"]["usd_per_index_point_per_lot"]
    long_, short_ = spec["swap_long"], spec["swap_short"]

    def pts(v, how):
        return {"points": v * pt,
                "currency": v / usd_per_idx_pt,
                "interest": price * v / 100 / 365}[how]

    readings = []
    for name, how, formula in [
        ("POINTS", "points", "swap x point"),
        ("CURRENCY_DEPOSIT (USD per lot per night)", "currency", "swap / (tick_value/tick_size)"),
        ("INTEREST_CURRENT (annual % of price)", "interest", "price x swap/100 / 365"),
    ]:
        pl, ps = pts(long_, how), pts(short_, how)
        readings.append({"reading of the numbers": name, "formula": formula, "long pts/night": round(pl, 4), "short pts/night": round(ps, 4),
                         "long % p.a.": round(100 * pl * 365 / price, 3), "short % p.a.": round(100 * ps * 365 / price, 3),
                         "plausible?": "yes" if abs(100 * pl * 365 / price) < 30 else "no - absurd financing rate"})
    pl = pts(long_, "points")
    ps = pts(short_, "points")
    day3 = spec["swap_rollover3days"]
    return {
        "mode": SWAP_MODES.get(mode, mode), "mode_code": mode, "swap_long_raw": long_, "swap_short_raw": short_,
        "swap_long_pts_per_night_if_points": round(pl, 4), "swap_short_pts_per_night_if_points": round(ps, 4),
        "annual_pct_long": round(100 * pl * 365 / price, 3), "annual_pct_short": round(100 * ps * 365 / price, 3),
        "price_used": price, "triple_day": DAYS.get(day3, day3), "triple_day_code": day3,
        "nights_per_week_charged": 7, "short_also_pays": bool(short_ < 0), "short_receives": bool(short_ > 0),
        "readings": pd.DataFrame(readings),
        "mode_disabled_but_values_present": bool(mode == 0 and (long_ != 0 or short_ != 0)),
        "landscape": landscape,
        "overnight_deals": deals.get("overnight", pd.DataFrame()),
    }
