# audit — US100 data and cost audit (IUX, MetaTrader 5)

Read-only measurement of what the data and broker conditions actually are. No order function is called anywhere;
no strategy, signal or backtest code is in this package. Results: [`report.md`](report.md), machine-readable inputs for the
next phase: [`out/cost_model_inputs.json`](out/cost_model_inputs.json) (every value tagged MEASURED / INFERRED / ASSUMED with N).

## Run

Needs Windows, Python 3.10+, a **logged-in MT5 terminal** (the IUX one is found automatically), and
`pip install MetaTrader5 pandas numpy pyarrow tzdata pytest`.

```
python -m audit.run            # from the repository root; ~1.5 min with a warm cache, ~10 min cold
python -m pytest audit/tests -q
```

Nothing is written outside `audit/`. Account login, password and balance are never read; only server name, currency,
leverage and account trade mode are recorded.

## Configuration (environment variables, all optional)

| variable | meaning |
|---|---|
| `MT5_TERMINAL_PATH` | path to `terminal64.exe` (default: auto-detect the IUX install from `%APPDATA%\MetaQuotes\Terminal\*\origin.txt`) |
| `AUDIT_SYMBOL` | symbol name (default: search for US100 / USTEC / NAS100 / NDX / NASDAQ; the run stops and asks if there is not exactly one candidate) |
| `AUDIT_EARLIEST_YEAR` | first year probed for history (default 2010) |
| `AUDIT_EVENTS_CSV` | optional `events.csv` with columns `event_name,datetime_et` to replace the approximate empirical event detection |
| `AUDIT_CACHE_DIR` | where raw pulls are cached (default `audit/cache/`, ~1 GB, gitignored; **note**: inside a OneDrive folder this is synced — move it if you do not want that) |

## Layout

| file | task |
|---|---|
| `mt5io.py` | connection, retrying chunked pulls (monthly bars, daily ticks), strict range filtering, parquet cache |
| `tickdigest.py` | per-day tick digest: per-minute time-weighted spread (LOCF), bid/ask OHLC, histograms, integrity counters |
| `tz.py` | era-aware server ↔ UTC ↔ New York helper (`ServerClock`), tested in `tests/test_tz.py` |
| `t0_preflight.py` … `t6_vol.py` | tasks 0–6 (preflight, coverage, spread, swap, time mapping, integrity, volatility and hurdles) |
| `report.py`, `run.py` | report/JSON/CSV generation and the entry point |

Cache layout: `cache/rates/<symbol>/<tf>/<YYYY-MM>.parquet`, `cache/ticks/<symbol>/<YYYY>/<date>.parquet` (prices as integer
points), `cache/digest_v1/...`. Delete a cache folder to force a re-pull; bump `DIGEST_VERSION` in `tickdigest.py` if the digest logic changes.

Using the measured server clock in later work:

```python
from audit.tz import ServerClock
clock = ServerClock.load("audit/out/server_clock.json")
et = clock.to_et(pd.DatetimeIndex(server_times))      # naive New York wall clock
```
