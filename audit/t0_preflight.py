"""Task 0: preflight. Full symbol specification, unit conversions, and read-only deal-history evidence for
commission and swap. Deal data is only aggregated: no tickets, order/position ids, login or balances are kept."""
import collections
import logging
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import pandas as pd

log = logging.getLogger("audit")
UTC = timezone.utc

SWAP_MODES = {0: "DISABLED", 1: "POINTS", 2: "CURRENCY_SYMBOL", 3: "CURRENCY_MARGIN", 4: "CURRENCY_DEPOSIT",
              5: "INTEREST_CURRENT", 6: "INTEREST_OPEN", 7: "REOPEN_CURRENT", 8: "REOPEN_BID"}
TRADE_MODES = {0: "DISABLED", 1: "LONGONLY", 2: "SHORTONLY", 3: "CLOSEONLY", 4: "FULL"}
CALC_MODES = {0: "FOREX", 1: "FUTURES", 2: "CFD", 3: "CFDINDEX", 4: "CFDLEVERAGE", 5: "FOREX_NO_LEVERAGE", 32: "EXCH_STOCKS"}
EXEC_MODES = {0: "REQUEST", 1: "INSTANT", 2: "MARKET", 3: "EXCHANGE"}
DAYS = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday"}


def _flags(v: int, names: dict) -> str:
    return "|".join(n for b, n in names.items() if v & b) or str(v)


def symbol_spec(sym: str) -> dict:
    si = mt5.symbol_info(sym)
    d = si._asdict()
    d["_decoded"] = {
        "swap_mode": SWAP_MODES.get(d["swap_mode"], d["swap_mode"]),
        "swap_rollover3days": DAYS.get(d["swap_rollover3days"], d["swap_rollover3days"]),
        "trade_mode": TRADE_MODES.get(d["trade_mode"], d["trade_mode"]),
        "trade_calc_mode": CALC_MODES.get(d["trade_calc_mode"], d["trade_calc_mode"]),
        "trade_exemode": EXEC_MODES.get(d["trade_exemode"], d["trade_exemode"]),
        "filling_mode": _flags(d["filling_mode"], {1: "FOK", 2: "IOC", 4: "BOC"}),
        "expiration_mode": _flags(d["expiration_mode"], {1: "GTC", 2: "DAY", 4: "SPECIFIED", 8: "SPECIFIED_DAY"}),
        "order_mode": _flags(d["order_mode"], {1: "MARKET", 2: "LIMIT", 4: "STOP", 8: "STOP_LIMIT", 16: "SL", 32: "TP", 64: "CLOSEBY"}),
    }
    pt, tsz, tval = d["point"], d["trade_tick_size"], d["trade_tick_value"]
    d["_units"] = {
        "index_point_in_price_units": 1.0,
        "point_in_price_units": pt,
        "points_per_index_point": round(1 / pt),
        "usd_per_index_point_per_lot": tval / tsz,          # tick_value is in account currency per tick per lot
        "note": "1 index point = 1.0 price unit = 1/point 'point' units. Costs below are in index points; "
                "multiply by usd_per_index_point_per_lot x lots for money.",
    }
    return d


def deal_evidence(sym: str) -> dict:
    """Aggregate read-only view of the account's own deal history: commission / fee / swap per symbol and overnight positions."""
    dl = mt5.history_deals_get(datetime(2015, 1, 1, tzinfo=UTC), datetime.now(UTC) + timedelta(days=2))
    if dl is None or len(dl) == 0:
        return {"deals": 0, "per_symbol": pd.DataFrame(), "overnight": pd.DataFrame(), "note": "no deal history available"}
    trades = [d for d in dl if d.symbol]
    rows = collections.defaultdict(lambda: collections.Counter())
    for d in trades:
        r = rows[d.symbol]
        r["deals"] += 1
        r["lots"] += d.volume
        r["commission"] += d.commission
        r["fee"] += d.fee
        r["swap"] += d.swap
        r["nonzero_commission_deals"] += d.commission != 0
    per_symbol = pd.DataFrame(rows).T.fillna(0).reset_index().rename(columns={"index": "symbol"})
    pos = collections.defaultdict(list)
    for d in trades:
        pos[d.position_id].append(d)
    over = []
    for ds in pos.values():
        ds.sort(key=lambda x: x.time)
        o, c = ds[0], ds[-1]
        if o.entry != 0 or c.entry != 1:
            continue
        t0, t1 = datetime.fromtimestamp(o.time, UTC), datetime.fromtimestamp(c.time, UTC)
        nights = (t1.date() - t0.date()).days                       # server-midnights crossed
        if nights >= 1:
            si = mt5.symbol_info(o.symbol)
            pts = (si.swap_long if o.type == 0 else si.swap_short) if si else float("nan")
            usd_per_pt = si.trade_tick_value / si.trade_tick_size * si.point if si else float("nan")    # per 1 'point' unit per lot
            over.append({"symbol": o.symbol, "direction": "long" if o.type == 0 else "short", "lots": o.volume, "nights": nights,
                         "swap_booked": sum(x.swap for x in ds),
                         "expected_if_points": round(o.volume * pts * usd_per_pt * nights, 5) if si else None})
    ours = [d for d in trades if d.symbol == sym]
    comm = sum(d.commission for d in ours)
    n_round_trips = sum(1 for d in ours if d.entry == 1)
    lots = sum(d.volume for d in ours if d.entry == 1)
    return {"deals": len(trades), "per_symbol": per_symbol, "overnight": pd.DataFrame(over),
            "sym_deals": len(ours), "sym_round_trips": n_round_trips, "sym_lots_closed": round(lots, 4), "sym_commission": comm,
            "sym_commission_per_lot_round_trip_usd": (comm / lots) if lots else None}


def swap_landscape() -> pd.DataFrame:
    """How swap_mode / swap values are configured across all symbols of the account (evidence for the mode-0 puzzle)."""
    rows = []
    for x in mt5.symbols_get():
        grp = x.path.split("\\")[1] if "\\" in x.path else ""
        rows.append({"group": grp, "swap_mode": SWAP_MODES.get(x.swap_mode, x.swap_mode),
                     "has_nonzero_swap_values": bool(x.swap_long != 0 or x.swap_short != 0)})
    df = pd.DataFrame(rows)
    return df.groupby(["group", "swap_mode"]).agg(symbols=("group", "size"), with_nonzero_swap_values=("has_nonzero_swap_values", "sum")).reset_index()
