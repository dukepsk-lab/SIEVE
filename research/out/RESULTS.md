# Phase 2 results: Stage A and Stage B (research/PLAN.md rules, frozen)

All numbers are **MEASURED** on USTEC. M1 **bid** bars from the audit cache (server clock converted to New York time). Slippage
is **ASSUMED** (0.5 / 2.0 points per side) and cannot be measured without live fills. Commission and swap are USER-CONFIRMED zero.
No bar stamped on or after 2026-01-01 ET was loaded into any variant, so Stage C (holdout) was not run and no 2026 result exists.
Run time of `python -m research.run_stages`: 2.1 s.

## Costs used

| item | points | provenance | bp of notional |
|---|---|---|---|
| P_REF (mean M1 close, 2026-05-14 to 2026-10-04) | 29,495.2 | MEASURED | n/a |
| round trip, base (spread 1.43 + 2 x 0.5) | 2.43 | spread MEASURED, slippage ASSUMED | 0.824 |
| round trip, stress (spread 2.0 + 2 x 2.0) | 6.00 | spread MEASURED, slippage ASSUMED | 2.034 |

Point-cost sensitivity ("net pt-cost"): the stress points divided by each trade's own entry price (harsher in early years).
Gates use the **stress** cost.

## Stage A: development, entry dates 2019-07-16 to 2023-12-31 (gate: net mean > 0, t >= 2.0, >= 3 of 5 calendar years positive)

| variant | role | trades | skipped | mean net stress bp | t | Sharpe | yrs+/yrs | gate |
|---|---|---|---|---|---|---|---|---|
| H1a | candidate | 872 | 58 | 4.97 | 1.59 | 0.74 | 4/5 | FAIL |
| H1b | candidate | 213 | 15 | -3.39 | -0.55 | -0.26 | 3/5 | FAIL |
| H2a | candidate | 1051 | 107 | -2.96 | -2.17 | -1.01 | 1/5 | FAIL |
| H2b | candidate | 561 | 107 | -2.18 | -1.03 | -0.48 | 1/5 | FAIL |
| H4a | candidate | 280 | 112 | -4.24 | -0.47 | -0.22 | 2/5 | FAIL |
| H4b | candidate | 141 | 111 | -19.32 | -1.50 | -0.70 | 1/5 | FAIL |
| H5a | candidate | 1038 | 120 | 3.74 | 0.71 | 0.33 | 3/5 | FAIL |
| H5b | candidate | 711 | 120 | 9.13 | 1.84 | 0.86 | 4/5 | FAIL |
| C1 | control | 1096 | 62 | 1.88 | 0.50 | 0.23 | 3/5 | control |
| C2 | control | 1099 | 59 | 8.11 | 1.61 | 0.75 | 4/5 | control |

Per trade (or per position-day for H5a, H5b, C2), bp:

| variant | trades/yr | gross | net base | net stress | net pt-cost | hit rate | max DD bp | total net stress bp |
|---|---|---|---|---|---|---|---|---|
| H1a | 195.40 | 7.01 | 6.18 | 4.97 | 1.92 | 0.55 | 2248.37 | 4335.85 |
| H1b | 47.73 | -1.36 | -2.18 | -3.39 | -6.44 | 0.51 | 1816.98 | -722.53 |
| H2a | 235.51 | -0.92 | -1.75 | -2.96 | -6.02 | 0.44 | 4449.13 | -3109.67 |
| H2b | 125.71 | -0.15 | -0.97 | -2.18 | -5.24 | 0.43 | 2095.63 | -1223.42 |
| H4a | 62.74 | -2.20 | -3.03 | -4.24 | -7.17 | 0.46 | 2676.46 | -1186.56 |
| H4b | 31.60 | -17.29 | -18.11 | -19.32 | -22.34 | 0.39 | 3403.18 | -2724.49 |
| H5a | 232.59 | 3.82 | 3.79 | 3.74 | 3.63 | 0.55 | 3668.76 | 3885.70 |
| H5b | 159.32 | 9.19 | 9.17 | 9.13 | 9.06 | 0.58 | 2736.20 | 6494.60 |
| C1 | 245.59 | 3.92 | 3.09 | 1.88 | -1.16 | 0.54 | 3234.00 | 2063.50 |
| C2 | 246.26 | 8.11 | 8.11 | 8.11 | 8.10 | 0.56 | 3965.64 | 8908.45 |

Net stress bp per calendar year (sum of daily P&L):

| variant | 2019 | 2020 | 2021 | 2022 | 2023 |
|---|---|---|---|---|---|
| H1a | 697.38 | 3256.39 | 901.45 | -1117.91 | 598.55 |
| H1b | 134.73 | 359.02 | -195.89 | -1259.76 | 239.37 |
| H2a | -373.49 | 865.47 | -1408.90 | -1488.70 | -704.05 |
| H2b | -325.81 | 472.89 | -405.66 | -331.89 | -632.96 |
| H4a | -136.10 | -1573.58 | 552.23 | -262.76 | 233.66 |
| H4b | -3.96 | -2321.88 | 457.07 | -805.29 | -50.44 |
| H5a | 633.96 | -935.64 | 3245.42 | -1713.65 | 2655.61 |
| H5b | 1004.36 | 1654.16 | 3006.67 | -2687.33 | 3516.73 |
| C1 | -416.31 | 945.46 | 593.78 | -1979.92 | 2920.49 |
| C2 | 1179.71 | 4243.97 | 2767.93 | -3661.01 | 4377.85 |

Skipped counts by reason:

| variant | skip_next_day_not_a_trading_day | skip_signal_unavailable | skip_missing_entry_price | skip_missing_exit_price |
|---|---|---|---|---|
| H1a | 6 | 0 | 47 | 5 |
| H1b | 0 | 0 | 10 | 5 |
| H2a | 0 | 66 | 41 | 0 |
| H2b | 0 | 107 | 0 | 0 |
| H4a | 0 | 109 | 0 | 3 |
| H4b | 0 | 109 | 0 | 2 |
| H5a | 0 | 61 | 59 | 0 |
| H5b | 0 | 61 | 59 | 0 |
| C1 | 0 | 0 | 11 | 51 |
| C2 | 0 | 0 | 59 | 0 |

### Stage A gate verdicts (8 candidates; controls are never candidates)

- H1a: **FAIL** (t = 1.59, mean net stress 4.97 bp, 4/5 years positive)
- H1b: **FAIL** (t = -0.55, mean net stress -3.39 bp, 3/5 years positive)
- H2a: **FAIL** (t = -2.17, mean net stress -2.96 bp, 1/5 years positive)
- H2b: **FAIL** (t = -1.03, mean net stress -2.18 bp, 1/5 years positive)
- H4a: **FAIL** (t = -0.47, mean net stress -4.24 bp, 2/5 years positive)
- H4b: **FAIL** (t = -1.50, mean net stress -19.32 bp, 1/5 years positive)
- H5a: **FAIL** (t = 0.71, mean net stress 3.74 bp, 3/5 years positive)
- H5b: **FAIL** (t = 1.84, mean net stress 9.13 bp, 4/5 years positive)

Survivors carried to Stage B: none.

## Stage B: validation, entry dates 2024-01-01 to 2025-12-31 (gate: net mean > 0, t >= 1.5)

No survivors: Stage B was not run.

## Definitions

- t = mean / std x sqrt(N_days) of the daily net stress P&L over every trading day of the window (0 on days without a position;
  P&L booked on the entry day). Sharpe = mean / std x sqrt(252). std uses ddof = 1.
- Controls: C1 = long 09:30 to 16:00 every day; C2 = buy and hold (one round trip per window). Reported only.
- Position variants (H5a, H5b, C2): "trades" = position-days (days with a non-zero position); each window starts and ends flat, so
  the entry and the final liquidation are charged; a flip costs one full round trip.
- The five Stage A calendar years are 2019 (partial, from 2019-07-16) to 2023.
- Stage C (2026-01-01 onward) is locked and untouched.
