# Phase 2 results, batch 2: Stage A and Stage B (research/PLAN.md section 9, frozen)

All numbers are **MEASURED** on USTEC. M1 **bid** bars from the audit cache (server clock converted to New York time). Slippage
is **ASSUMED** (0.5 / 2.0 points per side) and cannot be measured without live fills. Commission and swap are USER-CONFIRMED zero.
No bar stamped on or after 2026-01-01 ET was loaded into any variant, so Stage C (holdout) was not run and no 2026 result exists.
Run time of `python -m research.run_batch2`: 1.6 s. Frozen H6 constants: sigma* = 0.20, window = 20 returns, band = 0.10, H6a cap = 2.0, H6b cap = 1.0.

## Costs used

| item | points | provenance | bp of notional |
|---|---|---|---|
| P_REF (mean M1 close, current spread regime to 2026-10-04) | 29,495.2 | MEASURED | n/a |
| round trip, base (spread 1.43 + 2 x 0.5) | 2.43 | spread MEASURED, slippage ASSUMED | 0.824 |
| round trip, stress (spread 2.0 + 2 x 2.0) | 6.00 | spread MEASURED, slippage ASSUMED | 2.034 |

Every unit change in H6's weight w costs |change| x cost_bp / 2. The gates use the **stress** cost.

## Events file

`research/data/events.csv`, rows inside the market range 2019-07-16 to 2025-12-31 (first 2019-07-31, last 2025-12-18); only scheduled = True rows enter H3a, H8a and H8b:

| event | scheduled | rows |
|---|---|---|
| CPI | True | 76 |
| FOMC | False | 6 |
| FOMC | True | 51 |
| NFP | True | 76 |

## Stage A: development, entry dates 2019-07-16 to 2023-12-31
Gates: H6 = alpha vs C2 > 0 with Newey-West(5) t >= 2.0, Sharpe(H6) > Sharpe(C2), residual positive in >= 3 of 5 calendar years.
H3a, H8a, H8b = net stress mean > 0, daily-series t >= 2.0, >= 3 of 5 calendar years positive. Controls C2 and E0 are never candidates.

| variant | role | trades | skipped | mean net stress bp | t (daily) | Sharpe | yrs+/yrs | status |
|---|---|---|---|---|---|---|---|---|
| H6a | candidate | 1078 | 80 | 9.76 | 2.35 | 1.10 | 4/5 | PASS |
| H6b | candidate | 1078 | 80 | 7.53 | 2.09 | 0.98 | 4/5 | FAIL |
| H3a | candidate | 35 | 0 | 44.80 | 2.24 | 1.05 | 3/5 | PASS |
| H8a | candidate | 135 | 4 | 14.93 | 1.01 | 0.47 | 3/5 | FAIL |
| H8b | candidate | 102 | 4 | 1.94 | 0.16 | 0.08 | 3/5 | FAIL |
| C2 | control | 1099 | 59 | 8.11 | 1.61 | 0.75 | 4/5 | control |
| E0 | control | 912 | 103 | 5.72 | 1.03 | 0.48 | 4/5 | control |

Per trade (or per position-day for H6a, H6b, C2), bp:

| variant | trades/yr | gross | net base | net stress | net pt-cost | hit rate | max DD bp | total net stress bp |
|---|---|---|---|---|---|---|---|---|
| H6a | 241.56 | 9.78 | 9.77 | 9.76 | 9.72 | 0.56 | 3203.65 | 10519.26 |
| H6b | 241.56 | 7.54 | 7.53 | 7.53 | 7.51 | 0.56 | 2915.57 | 8115.36 |
| H3a | 7.84 | 46.83 | 46.01 | 44.80 | 41.80 | 0.63 | 368.90 | 1567.85 |
| H8a | 30.25 | 16.96 | 16.14 | 14.93 | 11.94 | 0.53 | 1572.89 | 2015.50 |
| H8b | 22.86 | 3.98 | 3.15 | 1.94 | -1.08 | 0.59 | 1613.65 | 198.20 |
| C2 | 246.26 | 8.11 | 8.11 | 8.11 | 8.10 | 0.56 | 3965.64 | 8908.45 |
| E0 | 204.36 | 7.75 | 6.93 | 5.72 | 2.66 | 0.56 | 3682.87 | 5217.28 |

H6 against the C2 benchmark (daily net stress bp; turnover = sum of |change in w| per year incl. entry and final exit):

| variant | alpha bp/day | alpha t (NW5) | beta vs C2 | Sharpe | Sharpe C2 | resid yrs+ | avg w | turnover/yr | w changes | status |
|---|---|---|---|---|---|---|---|---|---|---|
| H6a | 3.55 | 2.12 | 0.72 | 1.10 | 0.75 | 3/5 | 0.96 | 6.01 | 150 | PASS |
| H6b | 1.98 | 1.72 | 0.65 | 0.98 | 0.75 | 3/5 | 0.77 | 2.03 | 55 | FAIL |

Net stress bp per calendar year (sum of daily P&L):

| variant | 2019 | 2020 | 2021 | 2022 | 2023 |
|---|---|---|---|---|---|
| H6a | 2561.53 | 3028.10 | 3049.43 | -2718.46 | 4598.65 |
| H6b | 1646.09 | 2733.68 | 2405.07 | -2720.95 | 4051.48 |
| H3a | -56.44 | 530.23 | -152.87 | 1037.06 | 209.87 |
| H8a | 447.00 | -197.22 | 697.83 | -457.36 | 1525.24 |
| H8b | 120.47 | -640.59 | 730.96 | -664.36 | 651.72 |
| C2 | 1179.71 | 4243.97 | 2767.93 | -3661.01 | 4377.85 |
| E0 | 371.98 | 4261.37 | 948.61 | -3124.82 | 2760.14 |

H6 residual (variant - beta x C2) per calendar year, bp:

| variant | 2019 | 2020 | 2021 | 2022 | 2023 |
|---|---|---|---|---|---|
| H6a | 1712.98 | -24.54 | 1058.50 | -85.14 | 1449.71 |
| H6b | 874.56 | -41.87 | 594.85 | -326.66 | 1188.37 |

Skipped counts by reason:

| variant | skip_next_day_not_a_trading_day | skip_signal_unavailable | skip_missing_entry_price | skip_missing_exit_price |
|---|---|---|---|---|
| H6a | 0 | 21 | 59 | 0 |
| H6b | 0 | 21 | 59 | 0 |
| H3a | 0 | 0 | 0 | 0 |
| H8a | 0 | 1 | 1 | 2 |
| H8b | 0 | 1 | 1 | 2 |
| C2 | 0 | 0 | 59 | 0 |
| E0 | 0 | 1 | 58 | 44 |

Control E0 (report only): H8a - E0 mean per trade = 9.21 bp (H8a n = 135.00, E0 n = 912.00), Welch t = 0.58, df = 173.6. Per-trade net stress bp; the cost is the same on both sides, so the gross difference is identical.

### Stage A gate verdicts (5 candidates)

- H6a: **PASS** (alpha = 3.55 bp/day, t_NW = 2.12, beta = 0.72, Sharpe 1.10 vs C2 0.75, residual positive in 3/5 years)
- H6b: **FAIL** (alpha = 1.98 bp/day, t_NW = 1.72, beta = 0.65, Sharpe 0.98 vs C2 0.75, residual positive in 3/5 years)
- H3a: **PASS** (t = 2.24, mean net stress 44.80 bp, 3/5 years positive)
- H8a: **FAIL** (t = 1.01, mean net stress 14.93 bp, 3/5 years positive)
- H8b: **FAIL** (t = 0.16, mean net stress 1.94 bp, 3/5 years positive)

Survivors carried to Stage B: H6a, H3a.

## Stage B: validation, entry dates 2024-01-01 to 2025-12-31 (gate: H6 alpha > 0 and t_NW >= 1.5; events net stress mean > 0 and t >= 1.5)

| variant | role | trades | skipped | mean net stress bp | t (daily) | Sharpe | yrs+/yrs | status |
|---|---|---|---|---|---|---|---|---|
| H6a | candidate | 496 | 27 | 10.49 | 1.69 | 1.17 | 2/2 | FAIL |
| H3a | candidate | 16 | 0 | 23.41 | 0.90 | 0.63 | 2/2 | FAIL |

Per trade (or per position-day for H6a, H6b, C2), bp:

| variant | trades/yr | gross | net base | net stress | net pt-cost | hit rate | max DD bp | total net stress bp |
|---|---|---|---|---|---|---|---|---|
| H6a | 247.83 | 10.53 | 10.51 | 10.49 | 10.47 | 0.59 | 2350.15 | 5201.06 |
| H3a | 7.99 | 25.45 | 24.62 | 23.41 | 22.54 | 0.56 | 255.50 | 374.62 |

H6 against the C2 benchmark (daily net stress bp; turnover = sum of |change in w| per year incl. entry and final exit):

| variant | alpha bp/day | alpha t (NW5) | beta vs C2 | Sharpe | Sharpe C2 | resid yrs+ | avg w | turnover/yr | w changes | status |
|---|---|---|---|---|---|---|---|---|---|---|
| H6a | 1.40 | 0.72 | 0.96 | 1.17 | 1.09 | 1/2 | 1.14 | 9.55 | 92 | FAIL |

Net stress bp per calendar year (sum of daily P&L):

| variant | 2024 | 2025 |
|---|---|---|
| H6a | 3154.53 | 2046.53 |
| H3a | 358.88 | 15.74 |

H6 residual (variant - beta x C2) per calendar year, bp:

| variant | 2024 | 2025 |
|---|---|---|
| H6a | 736.04 | -5.61 |

Skipped counts by reason:

| variant | skip_next_day_not_a_trading_day | skip_signal_unavailable | skip_missing_entry_price | skip_missing_exit_price |
|---|---|---|---|---|
| H6a | 0 | 0 | 26 | 1 |
| H3a | 0 | 0 | 0 | 0 |

- H6a: **FAIL** (alpha = 1.40 bp/day, t_NW = 0.72, beta = 0.96, Sharpe 1.17 vs C2 1.09, residual positive in 1/2 years)
- H3a: **FAIL** (t = 0.90, mean net stress 23.41 bp, 2/2 years positive)

## Definitions and resolved ambiguities

- Daily series and t as in batch 1: every trading day of the window (0 where nothing is held or traded), P&L booked on the entry
  day, t = mean / std x sqrt(N_days), Sharpe = mean / std x sqrt(252), ddof = 1. Position variants (H6a, H6b, C2) count a
  position-day as a trade; each window starts and ends flat, so the entry and the final liquidation are charged.
- H6 alpha: OLS of the variant's daily net stress bp on C2's, same window, Newey-West standard errors (Bartlett kernel, 5 lags, no
  small-sample correction). The residual is the literal (variant - beta x C2), including the alpha, summed per calendar year.
- H6 starts flat; during the warm-up (21 valid closes: 20 returns plus the one-day lag) it holds nothing, while C2 is long from
  the first close. The band applies from the first available target (|target - 0| >= 0.10). A zero sigma_hat would give the cap.
- Event variants: d - 1 is the previous trading day of the market (no calendar-adjacency requirement); the FOMC statement time is
  fixed at 14:00 as in the plan (time_et is not used); events on non-trading days or with no previous trading day are skipped as
  "signal unavailable"; events outside the market range (before the first bar, or in the holdout) are ignored.
- E0 excludes every date that has an event row of any kind (scheduled or not) and is evaluated in Stage A only.
- Stage C (2026-01-01 onward) is locked and untouched. Batch 1 files are not modified by this run.
