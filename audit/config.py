"""Paths and constants. Everything overridable by environment variable so reruns need no code edits."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("AUDIT_CACHE_DIR", ROOT / "cache"))   # raw pulls (gitignored)
OUT = ROOT / "out"

TERMINAL_PATH = os.environ.get("MT5_TERMINAL_PATH", "")   # blank = auto-detect an IUX install
SYMBOL = os.environ.get("AUDIT_SYMBOL", "")               # blank = search for US100-like names
EARLIEST_YEAR = int(os.environ.get("AUDIT_EARLIEST_YEAR", "2010"))
EVENTS_CSV = os.environ.get("AUDIT_EVENTS_CSV", "")       # optional: event_name,datetime_et

BROKER_HINT = "IUX"                                       # terminal/company/server must contain this
SYMBOL_PATTERN = r"US100|USTEC|NAS100|NDX|NASDAQ|TECH ?100"

# USER-CONFIRMED by the account owner on 2026-10-05 (IUX Pro account): no commission, no swap on USTEC.
# Labelled USER-CONFIRMED in outputs. Override if the account terms change.
ACCOUNT_TYPE = "Pro"
USER_CONFIRMED_ON = "2026-10-05"
COMMISSION_RT_USD_PER_LOT = float(os.environ.get("AUDIT_COMMISSION_RT_USD", "0"))   # round trip, per 1.0 lot
SWAP_CHARGED = os.environ.get("AUDIT_SWAP_CHARGED", "0") == "1"

# ASSUMED (cannot be measured without live executions) -- always labelled ASSUMED in outputs
SLIP_BASE_PER_SIDE = 0.5      # index points
SLIP_STRESS_PER_SIDE = 2.0    # index points

# the user's earlier assumptions, for the comparison table in task 6
USER_ASSUMED = {
    "spread_base": 2.0, "spread_stress": 8.0, "swap_long_per_night": 4.6,
    "sigma": {"5min": 19, "1h": 65, "6h": 160, "overnight": 150, "5d": 700},
}

ET = "America/New_York"
