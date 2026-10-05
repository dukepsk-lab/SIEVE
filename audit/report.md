# USTEC. data and cost audit — IUX, MetaTrader 5
_Generated 2026-10-05 13:36 UTC · server clock at run 2026-10-05 14:36:18 · read-only audit (no order function was called) · all costs in **index points** (price units) unless stated; 1 index point = 100 `point` units._
Provenance tags: **MEASURED** = computed from MT5 data · **INFERRED** = derived with stated logic · **ASSUMED** = not measured. Sample sizes (N) sit next to every statistic.

## 1. Summary
**The data are clean enough to keep researching, but the cost side is a regime-risk problem and the measured numbers differ from your working assumptions in ways that matter.** History: 7.22 years of M1 bars and 5.14 years of ticks, with no duplicate or non-monotonic timestamps, no stale runs ≥ 5 min, and bars that are bid-based aggregates of the ticks; but the bar `spread` field is 0 before 2021-08, so spread history exists only for the tick era, and the server clock is **not** 'NY close' (0.0% of weeks match): it is UTC fixed (UTC+0) until 2021-10-25, then London (UTC+0/+1, EU DST), and the broker's session hours changed several times, so every time-of-day statistic must use the era-aware converter in `audit.tz`. Spread: it floated until early 2022 and since then is a broker-set quasi-fixed markup (re-set 28 times in the tick era, levels 0.6–3.0 pts), currently **1.43 pts** since 2026-05-14 (98.8% of minutes at exactly that value, p99 = 1.43, widest tick 2.0); older regimes show spikes to 69.3 pts around data releases and the daily re-open, so the risk is the broker changing the level, not intraday noise. Financing and commission are not settled: swap_mode is DISABLED although swap_long = -428.93 points is populated (read as points: long pays 4.2893 index pts/night = 5.066% p.a., short 0), and the account's deal history (one USTEC round trip, 0.0 commission) cannot tell whether either is charged — both are UNKNOWN and modelled conservatively. With measured volatility, required hit rates for a 1:1 payoff are 55.3% (5 min), 51.5% (1 h) and 50.6% (6 h) in the base case and 63.1/53.7/51.5% in the stress case (stress spread = the widest quote of the current regime, 2.0 pts; slippage 0.5/2 pts per side is ASSUMED). Every cell needs a lower hit rate than your assumptions. The improvement has two sources, a higher volatility in points and lower costs: of the 26.4 pp drop in the 5-min stress hurdle, 13.3 pp come from volatility and 13.1 pp from the spread (with measured volatility but your 8-pt stress spread, the 5-min stress hurdle would be 76.1%; section 9 splits every cell). The 2.0-pt stress spread rests on one 123-day regime and holds only while the broker does not re-price. No futures-roll jumps were found. **Verdict: data and costs support further research on horizons of about an hour and longer; sub-hour edges must beat 2.4–6.0 points per round trip and are sensitive to a spread re-pricing.**

## 2. Status of every question
| # | question | status | answer / what is missing |
|---|---|---|---|
| 0 | Symbol specification, units, point vs index points | ANSWERED | digits 2, point 0.01, 1 lot = 1 USD per index point |
| 0 | Commission | PARTIAL | 0.0 on the only USTEC round trip (n=1) and on all other deals; account type not exposed by the API → questions 1-2 |
| 1 | M1 earliest/latest, bars per day, gaps | ANSWERED | 2019-07-16 → now; gaps listed, mostly holidays/early closes |
| 1 | M5/H1/D1 earliest/latest | ANSWERED | same start date |
| 1 | Earliest tick, ticks/day, bid/ask, flags, last/volume | ANSWERED | from 2021-08-16; bid/ask always set; last/volume always 0; undocumented flag bits |
| 1 | Usable years and Sharpe floor (M1 and ticks) | ANSWERED | see table; assumes stationarity (violated) |
| 2 | Spread percentiles per 30-min bucket (server and ET) | ANSWERED | tick era only; current regime table + all-history CSV |
| 2 | Spread history before 2021-08 | UNKNOWN | bar spread field is 0 before 2021-08; needs another data source |
| 2 | Spread around the daily rollover | ANSWERED | spike at the re-open after the break (INFERRED rollover); −30 side is the closed break |
| 2 | Event-window spread and range (08:30 / 14:00 ET) | PARTIAL | APPROXIMATE: events detected empirically, no events file |
| 2 | Spread regime over time | ANSWERED | 29 regimes; structural level changes dated |
| 2 | Share of minutes > 2×/4×/8× session median | ANSWERED | table by year and for the current regime |
| 3 | Swap formula, points/night, triple day, annualised | PARTIAL | values computed; **whether swap is charged is UNKNOWN** (mode DISABLED with values populated) → question 3 |
| 3 | Rollover time | INFERRED | re-open spike time; the swap rollover time itself needs confirmation → question 4 |
| 4 | Live server offset | ANSWERED | UTC+1 now (London clock, EU summer time) |
| 4 | Server-time convention and offset regimes | ANSWERED | UTC-fixed → London time; NOT NY-close |
| 4 | Tested server→UTC→ET helper | ANSWERED | audit.tz + tests (DST transitions, mismatch weeks) |
| 5 | Duplicates, ordering, bid>ask, zero spread, stale, outside-session | ANSWERED | clean; details in section 8 |
| 5 | Outlier returns (past-only sigma) | ANSWERED | listed with timestamps |
| 5 | Roll / jump check | PARTIAL | no roll signature; cannot separate cash-like from adjusted futures |
| 5 | Bars vs ticks aggregation | ANSWERED | bid-based OHLC; tick_volume = tick count only approximately |
| 6 | Realised sigma by year and horizon | ANSWERED | tables by year; last-12-month sigma used |
| 6 | Hurdle table, measured vs your assumptions | PARTIAL | slippage ASSUMED; swap status UNKNOWN; stress spread = widest quote of the current regime; re-pricing risk shown as stress-alt |

## 3. Task 0 — Preflight (MEASURED)
Redacted terminal/account (login, name, balance, password are never read into the report):
| item | value | note |
|---|---|---|
| terminal | IUX Markets Limited · build 6230 · connected=True · algo trading allowed=False | terminal_info |
| server | IUXMarkets-Live | account_info |
| account currency | USD | account_info |
| leverage at run time | 3000 | account_info; **varies**: 400 and 3000 were both seen on the same day |
| account trade mode | REAL | REAL; the API does not expose the commercial account type (Pro/Standard/...) |
| margin mode | RETAIL_HEDGING | account_info |

Full symbol specification (`spread` here is the live snapshot in `point` units at run time):
| item | value | note |
|---|---|---|
| name | USTEC. |  |
| description | US Tech 100 Index |  |
| path | IUX Markets Pro\Index\USTEC. |  |
| digits | 2 |  |
| point | 0.01 |  |
| trade_tick_size | 0.01 |  |
| trade_tick_value | 0.01 |  |
| trade_tick_value_profit | 0.01 |  |
| trade_tick_value_loss | 0.01 |  |
| trade_contract_size | 1 |  |
| volume_min | 0.01 |  |
| volume_max | 250.00 |  |
| volume_step | 0.01 |  |
| currency_base | USD |  |
| currency_profit | USD |  |
| currency_margin | USD |  |
| spread | 143 |  |
| spread_float | True |  |
| trade_stops_level | 0 |  |
| trade_freeze_level | 300 |  |
| margin_initial | 0 |  |
| margin_maintenance | 0 |  |
| margin_hedged | 0 |  |
| swap_long | -428.93 |  |
| swap_short | 0 |  |
| session_deals | 0 |  |
| swap_mode | 0 | DISABLED |
| swap_rollover3days | 5 | Friday |
| trade_mode | 4 | FULL |
| trade_calc_mode | 2 | CFD |
| trade_exemode (execution) | 2 | MARKET |
| filling_mode | 3 | FOK/IOC |
| order_mode | 119 | MARKET/LIMIT/STOP/SL/TP/CLOSEBY |
| expiration_mode | 15 | GTC/DAY/SPECIFIED/SPECIFIED_DAY |

**Unit conversion.** `point`=0.01, tick size=0.01, so 1 index point = 100 points. Money per index point per 1.0 lot = tick_value/tick_size = **1.00 USD** (contract size 1.0). Smallest lot 0.01 = 0.01 USD per index point.

**Commission.** Not exposed in `symbol_info`. From the account's own deal history (read-only, aggregated):
| symbol | deals | lots | commission | fee | swap | nonzero_commission_deals |
|---|---|---|---|---|---|---|
| XAUUSD. | 77 | 1.83 | 0 | 0 | 0 | 0 |
| USTEC. | 2 | 0.04 | 0 | 0 | 0 | 0 |
On USTEC.: 2 deals, 1 round trip(s), 0.02 lots, commission booked = 0.0 → **0.0 per lot** (MEASURED, but n = 1 round trip, so weak). Other symbols also show 0.0 commission, which suggests a commission-free (spread-only) account type, but that is INFERRED, not confirmed — see questions.

## 4. Task 1 — History coverage
**Bars per timeframe (MEASURED).** Cross-check with a different API call: `copy_rates_from` asked for dates up to one year before the first bar returns the first bar itself and nothing earlier (0 earlier bars). MT5 answers out-of-range requests with the nearest available bar (a request for year 2010 returned a 2019 bar), so every pull is filtered strictly to the requested range.
| timeframe | bars | first_bar_server | last_bar_server | earlier_bars_found (copy_rates_from, 1y before) | years |
|---|---|---|---|---|---|
| D1 | 2,241 | 2019-07-16 00:00 | 2026-10-04 00:00 | 0 | 7.22 |
| H1 | 41,822 | 2019-07-16 07:00 | 2026-10-05 13:00 | 0 | 7.22 |
| M5 | 494,852 | 2019-07-16 07:55 | 2026-10-05 14:30 | 0 | 7.22 |
| M1 | 2,471,212 | 2019-07-16 07:59 | 2026-10-05 14:35 | 0 | 7.22 |

**M1 coverage vs expected session minutes (MEASURED / INFERRED schedule).** The expected schedule is inferred per calendar quarter in New York time: a minute is 'expected' when ≥50% of open days have a bar there. Expected minutes 2,525,528, missing 57,739 (2.29%). Bars outside the inferred schedule: 3,423.
| year | open_days | mean_bars | mean_expected | mean_ratio | days_below_95pct |
|---|---|---|---|---|---|
| 2019 | 143 | 1,097.0 | 1,136.0 | 96.5 | 14 |
| 2020 | 310 | 1,079.0 | 1,106.0 | 97.69 | 43 |
| 2021 | 310 | 1,064.0 | 1,077.0 | 98.74 | 18 |
| 2022 | 308 | 1,105.0 | 1,119.0 | 98.8 | 18 |
| 2023 | 310 | 1,086.0 | 1,098.0 | 98.97 | 17 |
| 2024 | 313 | 1,132.0 | 1,151.0 | 98.58 | 15 |
| 2025 | 312 | 1,124.0 | 1,148.0 | 98.21 | 17 |
| 2026 | 238 | 1,125.0 | 1,138.0 | 98.95 | 8 |

Session schedule history (ET), INFERRED from where bars exist (daily break = minutes with no bars). The broker changed its hours several times:
| from | to | daily break (ET, expected-minute gap) |
|---|---|---|
| 2019Q3 | 2019Q3 | 12:15-12:29, 16:15-16:29, 17:00-17:59, 20:00-20:14 |
| 2019Q4 | 2019Q4 | 16:15-16:29, 17:00-17:59 |
| 2020Q1 | 2020Q2 | 16:15-16:29, 16:59-17:59 |
| 2020Q3 | 2020Q4 | 16:00-18:29 |
| 2021Q1 | 2022Q1 | 15:59-18:29 |
| 2022Q2 | 2022Q3 | 16:15-16:29, 16:59-17:59 |
| 2022Q4 | 2022Q4 | 15:59-17:59 |
| 2023Q1 | 2023Q3 | 15:59-18:29 |
| 2023Q4 | 2025Q1 | 16:59-17:59 |
| 2025Q2 | 2025Q2 | 17:00-17:59 |
| 2025Q3 | 2026Q3 | 16:58-18:04 |

Expected session minutes in 2026Q3 (ET), the latest quarter with enough days:
| weekday_ET | from_ET | to_ET | minutes |
|---|---|---|---|
| Mon | 00:00 | 16:57 | 1,018 |
| Mon | 18:05 | 23:59 | 355 |
| Tue | 00:00 | 16:57 | 1,018 |
| Tue | 18:05 | 23:59 | 355 |
| Wed | 00:00 | 16:57 | 1,018 |
| Wed | 18:05 | 23:59 | 355 |
| Thu | 00:00 | 16:57 | 1,018 |
| Thu | 18:05 | 23:59 | 355 |
| Fri | 00:00 | 16:54 | 1,015 |
| Sun | 18:05 | 23:59 | 355 |

Gaps by size (a gap = run of expected minutes with no bar; '>1 min' = at least 1 missing minute, '>5' = at least 5, '>60' = at least 60). Gaps are measured against the quarterly schedule, weekends and the daily break are excluded:
| year | >1 min | >5 min | >60 min | >60 min, excluding holiday closures / early closes |
|---|---|---|---|---|
| 2019 | 159 | 143 | 11 | 2 |
| 2020 | 198 | 143 | 26 | 12 |
| 2021 | 142 | 63 | 22 | 3 |
| 2022 | 101 | 74 | 32 | 18 |
| 2023 | 123 | 29 | 19 | 5 |
| 2024 | 105 | 36 | 13 | 0 |
| 2025 | 103 | 36 | 23 | 3 |
| 2026 | 50 | 16 | 7 | 0 |
| all | 981 | 540 | 153 | 43 |

**20 largest gaps** (times in New York and server clock). Gaps ≥ 10 h are holiday closures or outages; gaps that run to the daily break are US-holiday early closes; 110 of 981 gaps are of those two kinds, the rest ('other') are intraday data gaps:
| start_et | end_et | start_server | minutes_missing | kind |
|---|---|---|---|---|
| 2023-12-24 18:00 | 2023-12-25 16:58 | 2023-12-24 23:00 | 1,379 | closure >=10h (holiday or outage) |
| 2023-12-31 18:00 | 2024-01-01 16:58 | 2023-12-31 23:00 | 1,379 | closure >=10h (holiday or outage) |
| 2024-12-24 18:00 | 2024-12-25 16:58 | 2024-12-24 23:00 | 1,379 | closure >=10h (holiday or outage) |
| 2024-12-31 18:00 | 2025-01-01 16:58 | 2024-12-31 23:00 | 1,379 | closure >=10h (holiday or outage) |
| 2024-03-28 18:00 | 2024-03-29 16:54 | 2024-03-28 22:00 | 1,375 | closure >=10h (holiday or outage) |
| 2025-04-17 18:00 | 2025-04-18 16:54 | 2025-04-17 23:00 | 1,375 | closure >=10h (holiday or outage) |
| 2025-12-24 18:05 | 2025-12-25 16:57 | 2025-12-24 23:05 | 1,373 | closure >=10h (holiday or outage) |
| 2025-12-31 18:05 | 2026-01-01 16:57 | 2025-12-31 23:05 | 1,373 | closure >=10h (holiday or outage) |
| 2019-12-24 18:00 | 2019-12-25 16:14 | 2019-12-24 23:00 | 1,335 | closure >=10h (holiday or outage) |
| 2019-12-25 18:00 | 2019-12-26 16:14 | 2019-12-25 23:00 | 1,335 | closure >=10h (holiday or outage) |
| 2022-12-25 18:00 | 2022-12-26 15:58 | 2022-12-25 23:00 | 1,319 | closure >=10h (holiday or outage) |
| 2020-04-09 18:30 | 2020-04-10 16:14 | 2020-04-09 22:30 | 1,305 | closure >=10h (holiday or outage) |
| 2020-04-30 18:30 | 2020-05-01 16:14 | 2020-04-30 22:30 | 1,305 | closure >=10h (holiday or outage) |
| 2020-12-24 18:30 | 2020-12-25 15:59 | 2020-12-24 23:30 | 1,290 | closure >=10h (holiday or outage) |
| 2020-12-31 18:30 | 2021-01-01 15:59 | 2020-12-31 23:30 | 1,290 | closure >=10h (holiday or outage) |
| 2021-12-23 18:30 | 2021-12-24 15:58 | 2021-12-23 23:30 | 1,289 | closure >=10h (holiday or outage) |
| 2023-01-01 18:30 | 2023-01-02 15:58 | 2023-01-01 23:30 | 1,289 | closure >=10h (holiday or outage) |
| 2019-12-31 18:00 | 2020-01-01 11:14 | 2019-12-31 23:00 | 1,035 | closure >=10h (holiday or outage) |
| 2020-03-15 18:23 | 2020-03-16 09:47 | 2020-03-15 22:23 | 925 | closure >=10h (holiday or outage) |
| 2021-09-12 18:30 | 2021-09-13 08:41 | 2021-09-12 22:30 | 852 | closure >=10h (holiday or outage) |

Largest 'other' gaps (not holiday closures or early closes):
| start_et | end_et | start_server | minutes_missing |
|---|---|---|---|
| 2022-11-20 18:00 | 2022-11-21 03:41 | 2022-11-20 23:00 | 582 |
| 2022-04-03 18:00 | 2022-04-04 03:35 | 2022-04-03 23:00 | 576 |
| 2020-03-18 01:18 | 2020-03-18 09:30 | 2020-03-18 05:18 | 493 |
| 2025-11-27 22:25 | 2025-11-28 06:02 | 2025-11-28 03:25 | 458 |
| 2020-03-16 22:30 | 2020-03-17 04:25 | 2020-03-17 02:30 | 356 |
| 2022-04-15 00:00 | 2022-04-15 05:36 | 2022-04-15 05:00 | 337 |
| 2022-12-26 18:00 | 2022-12-26 22:33 | 2022-12-26 23:00 | 274 |
| 2022-04-14 18:00 | 2022-04-14 22:23 | 2022-04-14 23:00 | 264 |
| 2020-03-09 05:47 | 2020-03-09 09:24 | 2020-03-09 09:47 | 218 |
| 2023-07-16 18:30 | 2023-07-16 22:07 | 2023-07-16 23:30 | 218 |
| 2019-08-02 02:58 | 2019-08-02 05:45 | 2019-08-02 06:58 | 168 |
| 2025-11-28 06:04 | 2025-11-28 08:49 | 2025-11-28 11:04 | 166 |
| 2020-03-09 03:01 | 2020-03-09 05:20 | 2020-03-09 07:01 | 140 |
| 2023-01-25 03:28 | 2023-01-25 05:43 | 2023-01-25 08:28 | 136 |
| 2019-07-28 18:00 | 2019-07-28 20:14 | 2019-07-28 22:00 | 135 |
| 2020-03-13 07:11 | 2020-03-13 09:24 | 2020-03-13 11:11 | 134 |
| 2020-03-08 23:58 | 2020-03-09 01:55 | 2020-03-09 03:58 | 118 |
| 2022-04-15 05:38 | 2022-04-15 07:33 | 2022-04-15 10:38 | 116 |
| 2020-09-06 18:30 | 2020-09-06 20:17 | 2020-09-06 22:30 | 108 |
| 2025-02-05 18:00 | 2025-02-05 19:32 | 2025-02-05 23:00 | 93 |

**Ticks (MEASURED).** Earliest tick: **2021-08-16 13:54:26.625000** server time (binary search over weeks; direct `copy_ticks_from` from 2019 gives 2021-08-16 13:54:26.625000). 237,946,841 ticks on 1597 days between 2021-08-16 and 2026-10-04.
- bid and ask both > 0 on **100.0%** of ticks · `last` non-zero on 0 · `volume` non-zero on 0 · `volume_real` non-zero on 0 (CFD: price-only ticks, no traded volume).
- flags: bits 2/4 are BID/ASK; bits 128 and 1024 are **undocumented** broker bits. The mix changes in 2025, which marks a feed/platform change:
| flags | ticks | decoded | share_pct |
|---|---|---|---|
| 1,158 | 135,413,070 | BID+ASK +undocumented bits 1152 | 56.909 |
| 134 | 100,462,169 | BID+ASK +undocumented bits 128 | 42.22 |
| 130 | 728,068 | BID +undocumented bits 128 | 0.306 |
| 4 | 663,903 | ASK | 0.279 |
| 1,030 | 441,122 | BID+ASK +undocumented bits 1024 | 0.185 |
| 6 | 195,751 | BID+ASK | 0.082 |
| 1,154 | 21,492 | BID +undocumented bits 1152 | 0.009 |
| 1,028 | 21,113 | ASK +undocumented bits 1024 | 0.009 |
| 2 | 153 | BID | 0 |
| year | 2 | 4 | 6 | 130 | 134 | 1028 | 1030 | 1154 | 1158 |
|---|---|---|---|---|---|---|---|---|---|
| 2021 | 13 | 3,648 | 26,442 | 3,673 | 4,269,834 | 0 | 0 | 0 | 0 |
| 2022 | 0 | 449,934 | 0 | 501,552 | 43,349,109 | 0 | 0 | 0 | 0 |
| 2023 | 140 | 87,977 | 169,221 | 83,602 | 20,824,794 | 0 | 0 | 0 | 0 |
| 2024 | 0 | 122,166 | 88 | 138,742 | 29,266,281 | 0 | 0 | 0 | 0 |
| 2025 | 0 | 178 | 0 | 499 | 2,752,151 | 21,104 | 441,122 | 21,376 | 43,972,588 |
| 2026 | 0 | 0 | 0 | 0 | 0 | 9 | 0 | 116 | 91,440,482 |

Ticks per day by month (days with ticks only):
| month | days | ticks_total | ticks_per_day_mean | ticks_per_day_min | ticks_per_day_max |
|---|---|---|---|---|---|
| 2021-08 | 13 | 399,103 | 30,700 | 1,038 | 54,727 |
| 2021-09 | 25 | 900,315 | 36,013 | 743 | 56,675 |
| 2021-10 | 26 | 982,789 | 37,800 | 1,879 | 62,691 |
| 2021-11 | 26 | 902,325 | 34,705 | 420 | 63,176 |
| 2021-12 | 26 | 1,119,078 | 43,041 | 654 | 68,513 |
| 2022-01 | 26 | 4,324,534 | 166,328 | 541 | 395,442 |
| 2022-02 | 24 | 5,692,648 | 237,194 | 2,225 | 478,751 |
| 2022-03 | 27 | 5,953,071 | 220,484 | 2,252 | 382,906 |
| 2022-04 | 25 | 5,225,859 | 209,034 | 2 | 374,557 |
| 2022-05 | 27 | 5,836,025 | 216,149 | 2,590 | 398,185 |
| 2022-06 | 26 | 2,805,970 | 107,922 | 2,995 | 154,654 |
| 2022-07 | 26 | 2,413,294 | 92,819 | 1,671 | 136,370 |
| 2022-08 | 27 | 2,409,965 | 89,258 | 1,128 | 126,013 |
| 2022-09 | 26 | 2,728,593 | 104,946 | 1,804 | 155,173 |
| 2022-10 | 26 | 2,712,741 | 104,336 | 3,035 | 145,748 |
| 2022-11 | 25 | 2,193,139 | 87,726 | 1,030 | 121,986 |
| 2022-12 | 24 | 2,004,756 | 83,532 | 780 | 114,603 |
| 2023-01 | 26 | 1,865,930 | 71,767 | 806 | 113,011 |
| 2023-02 | 24 | 1,860,858 | 77,536 | 695 | 114,891 |
| 2023-03 | 27 | 2,463,982 | 91,259 | 715 | 147,484 |
| 2023-04 | 25 | 1,828,095 | 73,124 | 334 | 104,098 |
| 2023-05 | 27 | 2,061,398 | 76,348 | 327 | 108,814 |
| 2023-06 | 26 | 1,913,760 | 73,606 | 53 | 144,782 |
| 2023-07 | 25 | 1,467,342 | 58,694 | 433 | 88,551 |
| 2023-08 | 27 | 1,895,577 | 70,207 | 485 | 90,381 |
| 2023-09 | 25 | 1,645,666 | 65,827 | 301 | 93,219 |
| 2023-10 | 27 | 1,681,239 | 62,268 | 1,566 | 100,670 |
| 2023-11 | 26 | 1,236,654 | 47,564 | 1,190 | 63,239 |
| 2023-12 | 24 | 1,245,233 | 51,885 | 1,255 | 86,037 |
| 2024-01 | 27 | 2,490,293 | 92,233 | 1,340 | 162,493 |
| 2024-02 | 25 | 2,325,752 | 93,030 | 2,102 | 150,115 |
| 2024-03 | 26 | 2,217,993 | 85,307 | 1 | 129,143 |
| 2024-04 | 26 | 2,757,549 | 106,060 | 2,233 | 170,189 |
| 2024-05 | 27 | 2,443,348 | 90,494 | 1,199 | 132,207 |
| 2024-06 | 25 | 2,239,368 | 89,575 | 1,582 | 126,822 |
| 2024-07 | 27 | 2,749,127 | 101,820 | 2,085 | 165,289 |
| 2024-08 | 26 | 2,905,841 | 111,763 | 3,371 | 171,502 |
| 2024-09 | 26 | 2,605,038 | 100,194 | 2,083 | 158,750 |
| 2024-10 | 27 | 2,435,212 | 90,193 | 1,882 | 122,738 |
| 2024-11 | 25 | 2,279,106 | 91,164 | 2,440 | 150,354 |
| 2024-12 | 27 | 2,078,650 | 76,987 | 2,266 | 147,224 |
| 2025-01 | 27 | 2,514,630 | 93,134 | 3,004 | 153,025 |
| 2025-02 | 24 | 2,954,029 | 123,085 | 3,621 | 238,536 |
| 2025-03 | 26 | 4,334,310 | 166,704 | 6,203 | 257,370 |
| 2025-04 | 25 | 5,611,862 | 224,474 | 4,152 | 340,405 |
| 2025-05 | 26 | 4,380,239 | 168,471 | 5,907 | 250,053 |
| 2025-06 | 26 | 3,846,442 | 147,940 | 5,092 | 247,620 |
| 2025-07 | 27 | 3,310,894 | 122,626 | 2,939 | 187,734 |
| 2025-08 | 26 | 3,421,757 | 131,606 | 2,918 | 236,557 |
| 2025-09 | 26 | 3,476,097 | 133,696 | 2,343 | 207,772 |
| 2025-10 | 27 | 4,471,751 | 165,620 | 4,541 | 283,439 |
| 2025-11 | 25 | 4,972,760 | 198,910 | 5,746 | 342,187 |
| 2025-12 | 27 | 3,914,247 | 144,972 | 3,345 | 289,614 |
| 2026-01 | 26 | 4,826,346 | 185,629 | 4,933 | 360,288 |
| 2026-02 | 24 | 5,743,928 | 239,330 | 7,281 | 393,144 |
| 2026-03 | 27 | 10,418,933 | 385,886 | 14,518 | 540,168 |
| 2026-04 | 26 | 8,599,891 | 330,765 | 13,288 | 613,621 |
| 2026-05 | 26 | 11,360,428 | 436,940 | 14,595 | 632,273 |
| 2026-06 | 26 | 12,855,558 | 494,445 | 17,195 | 659,406 |
| 2026-07 | 27 | 13,261,633 | 491,172 | 13,209 | 658,993 |
| 2026-08 | 26 | 11,226,450 | 431,787 | 7,365 | 599,220 |
| 2026-09 | 26 | 11,927,138 | 458,736 | 3,657 | 607,328 |
| 2026-10 | 3 | 1,220,302 | 406,767 | 11,381 | 621,600 |

**Usable history and minimum detectable Sharpe (t = 3 → 3/√years, MEASURED years):**
| source | years | min_detectable_sharpe_t3 |
|---|---|---|
| M1 bars | 7.22 | 1.12 |
| ticks | 5.14 | 1.32 |
The Sharpe floor assumes stationarity; here spread level, server clock, session hours and feed density all changed, so the effective independent sample is shorter than the calendar span.

## 5. Task 2 — Spread audit (ticks, 2021-08 onward)
Primary measure: per-minute **time-weighted median spread** with last-observation-carried-forward (MEASURED from 1,772,189 tick-minutes). Ticks with bid or ask ≤ 0 are ignored; crossed quotes (ask < bid) are counted and excluded. Tick-weighted numbers appear only as a comparison.

### 2d. Spread regimes (structural changes)
Daily modal spread, split into regimes whenever 5 consecutive days deviate ≥4% from the running level (**29 regimes**). `pct_minutes_at_modal_value` = share of minutes whose spread equals the regime's most common value. Before 2022-01-11 the spread **floated** (≤5.2% of minutes at any single value); from 2022-01-11 it is a **broker-set quasi-fixed markup** — every regime of ≥ 10 days has ≥ 85.8% of minutes at one value — that is re-set in steps, not a market-driven quantity:
| start | end | days | level_pts | minutes | pct_minutes_at_modal_value | p50 | p99 | p99.9 | max_tick |
|---|---|---|---|---|---|---|---|---|---|
| 2021-08-16 | 2021-09-07 | 20 | 0.56 | 19,742 | 4.4 | 0.58 | 1 | 1.29 | 2.8 |
| 2021-09-08 | 2021-09-27 | 16 | 0.67 | 17,134 | 3.9 | 0.71 | 1.26 | 1.67 | 3.7 |
| 2021-09-28 | 2021-10-06 | 8 | 0.72 | 8,995 | 3.6 | 0.77 | 1.26 | 1.56 | 2.37 |
| 2021-10-07 | 2021-11-03 | 24 | 0.66 | 25,772 | 5.2 | 0.69 | 1.13 | 1.45 | 2.69 |
| 2021-11-04 | 2021-11-18 | 13 | 0.81 | 13,938 | 4.8 | 0.82 | 1.22 | 1.6 | 2.35 |
| 2021-11-19 | 2021-11-29 | 9 | 0.86 | 8,517 | 3.4 | 0.92 | 1.58 | 2.86 | 6.69 |
| 2021-11-30 | 2021-12-08 | 8 | 0.99 | 9,007 | 3.7 | 1.03 | 1.8 | 2.17 | 3.41 |
| 2021-12-09 | 2021-12-14 | 5 | 0.83 | 5,156 | 3.1 | 0.89 | 1.55 | 1.78 | 2.67 |
| 2021-12-15 | 2021-12-20 | 5 | 0.98 | 5,156 | 3.1 | 1.02 | 1.9 | 2.65 | 3.3 |
| 2021-12-21 | 2021-12-27 | 5 | 0.8 | 5,156 | 4.6 | 0.85 | 1.34 | 1.65 | 2.01 |
| 2021-12-28 | 2022-01-04 | 7 | 0.89 | 7,674 | 4.6 | 0.89 | 1.75 | 2.16 | 2.56 |
| 2022-01-05 | 2022-01-10 | 5 | 0.96 | 5,156 | 5.1 | 1.01 | 2.26 | 2.54 | 4.18 |
| 2022-01-11 | 2022-05-23 | 114 | 2.15 | 122,157 | 86.2 | 2.15 | 3.1 | 3.4 | 10.9 |
| 2022-05-24 | 2022-08-31 | 86 | 0.6 | 97,460 | 98.1 | 0.6 | 1.1 | 2.35 | 20 |
| 2022-09-01 | 2023-05-17 | 219 | 0.7 | 236,788 | 98.6 | 0.7 | 0.7 | 2.2 | 69.3 |
| 2023-05-18 | 2023-12-17 | 183 | 1.52 | 200,501 | 95.6 | 1.52 | 1.9 | 3.16 | 19.65 |
| 2023-12-18 | 2024-01-21 | 28 | 1.62 | 31,373 | 85.8 | 1.62 | 2.92 | 2.92 | 12 |
| 2024-01-22 | 2024-03-03 | 36 | 2.92 | 41,091 | 99.3 | 2.92 | 2.92 | 3.42 | 12 |
| 2024-03-04 | 2024-07-22 | 121 | 2.6 | 136,862 | 98.4 | 2.6 | 2.92 | 3.6 | 15 |
| 2024-07-23 | 2024-10-27 | 83 | 3 | 94,715 | 91 | 3 | 5 | 6.5 | 15 |
| 2024-10-28 | 2024-12-10 | 38 | 1 | 43,482 | 98 | 1 | 2 | 3 | 8.35 |
| 2024-12-11 | 2024-12-18 | 7 | 1.14 | 8,268 | 97.8 | 1.14 | 1.21 | 2 | 7.2 |
| 2024-12-19 | 2025-01-17 | 26 | 1.21 | 26,525 | 99.9 | 1.21 | 1.21 | 1.21 | 7.2 |
| 2025-01-19 | 2025-01-23 | 5 | 1.4 | 5,634 | 42.5 | 1.2 | 1.4 | 1.4 | 2 |
| 2025-01-24 | 2025-12-16 | 279 | 1.12 | 315,882 | 90.2 | 1.12 | 1.3 | 1.56 | 7.2 |
| 2025-12-17 | 2025-12-28 | 10 | 1.21 | 9,340 | 93.1 | 1.21 | 1.21 | 1.21 | 1.65 |
| 2025-12-29 | 2026-03-18 | 69 | 1.14 | 77,630 | 95.7 | 1.14 | 1.2 | 2 | 2 |
| 2026-03-19 | 2026-05-13 | 48 | 1.36 | 54,396 | 98.8 | 1.36 | 1.36 | 1.36 | 2 |
| 2026-05-14 | 2026-10-04 | 123 | 1.43 | 138,682 | 98.8 | 1.43 | 1.43 | 1.43 | 2 |

Monthly median / p99 of the per-minute spread (index points). Before 2021-08 only the bar `spread` field exists and it is **0 in 100% of bars in 2019-2020 and 63% of 2021** (MEASURED) → spread history before 2021-08 is **UNKNOWN**. From 2021-08 the bar field is a single snapshot per bar and is biased low (see bar-vs-tick table).
25 months from 2019-07 to 2021-07: bar spread = 0 in every bar, no tick history → no spread information (omitted from the table).
| month | bars_median | bars_p99 | tick_median | tick_p99 | tick_max | tick_N | primary_source |
|---|---|---|---|---|---|---|---|
| 2021-08 | 0 | 0.86 | 0.57 | 1.01 | 2.3 | 13,264 | ticks |
| 2021-09 | 0.68 | 1.13 | 0.69 | 1.21 | 3.7 | 27,225 | ticks |
| 2021-10 | 0.68 | 1.09 | 0.69 | 1.18 | 2.69 | 27,048 | ticks |
| 2021-11 | 0.82 | 1.4 | 0.84 | 1.49 | 6.69 | 27,535 | ticks |
| 2021-12 | 0.92 | 1.64 | 0.94 | 1.75 | 3.41 | 28,267 | ticks |
| 2022-01 | 2.06 | 2.15 | 2.15 | 2.8 | 10.85 | 26,740 | ticks |
| 2022-02 | 2.15 | 2.15 | 2.15 | 3.1 | 10.9 | 25,520 | ticks |
| 2022-03 | 2.15 | 2.15 | 2.15 | 3.1 | 10.9 | 29,600 | ticks |
| 2022-04 | 2.15 | 2.15 | 2.15 | 2.15 | 10.9 | 26,179 | ticks |
| 2022-05 | 2.15 | 2.15 | 2.15 | 2.6 | 13.15 | 29,837 | ticks |
| 2022-06 | 0.6 | 0.6 | 0.6 | 1.1 | 20 | 29,749 | ticks |
| 2022-07 | 0.6 | 0.6 | 0.6 | 0.6 | 20 | 28,398 | ticks |
| 2022-08 | 0.6 | 0.6 | 0.6 | 0.85 | 20 | 31,358 | ticks |
| 2022-09 | 0.7 | 0.7 | 0.7 | 0.7 | 20 | 29,716 | ticks |
| 2022-10 | 0.7 | 0.7 | 0.7 | 0.7 | 19.15 | 28,654 | ticks |
| 2022-11 | 0.7 | 1.338 | 0.7 | 1.6 | 20 | 27,826 | ticks |
| 2022-12 | 0.7 | 0.7 | 0.7 | 0.7 | 64.7 | 26,745 | ticks |
| 2023-01 | 0.7 | 0.7 | 0.7 | 0.7 | 28.2 | 26,706 | ticks |
| 2023-02 | 0.7 | 0.7 | 0.7 | 0.7 | 15.2 | 25,569 | ticks |
| 2023-03 | 0.7 | 0.7 | 0.7 | 2.2 | 69.3 | 29,495 | ticks |
| 2023-04 | 0.7 | 0.7 | 0.7 | 0.7 | 11.5 | 25,336 | ticks |
| 2023-05 | 0.7 | 1.52 | 0.7 | 1.52 | 14 | 29,452 | ticks |
| 2023-06 | 1.52 | 1.9 | 1.52 | 1.9 | 12.12 | 28,085 | ticks |
| 2023-07 | 1.52 | 1.72 | 1.52 | 1.82 | 15.91 | 26,513 | ticks |
| 2023-08 | 1.52 | 1.52 | 1.52 | 1.52 | 15.26 | 29,584 | ticks |
| 2023-09 | 1.52 | 1.52 | 1.52 | 1.52 | 19.65 | 28,176 | ticks |
| 2023-10 | 1.52 | 1.52 | 1.52 | 1.52 | 11.51 | 30,451 | ticks |
| 2023-11 | 1.52 | 1.52 | 1.52 | 1.52 | 13.17 | 29,816 | ticks |
| 2023-12 | 1.52 | 1.62 | 1.52 | 1.62 | 18.26 | 27,475 | ticks |
| 2024-01 | 1.62 | 2.92 | 1.62 | 2.92 | 12 | 30,089 | ticks |
| 2024-02 | 2.92 | 2.92 | 2.92 | 2.92 | 12 | 28,708 | ticks |
| 2024-03 | 2.6 | 2.92 | 2.6 | 2.92 | 14.2 | 27,536 | ticks |
| 2024-04 | 2.6 | 2.6 | 2.6 | 2.6 | 14.2 | 30,328 | ticks |
| 2024-05 | 2.6 | 2.6 | 2.6 | 2.6 | 15 | 31,405 | ticks |
| 2024-06 | 2.6 | 2.6 | 2.6 | 2.6 | 15 | 27,390 | ticks |
| 2024-07 | 2.6 | 3 | 2.6 | 3 | 15 | 31,192 | ticks |
| 2024-08 | 3 | 3 | 3 | 5.5 | 15 | 30,240 | ticks |
| 2024-09 | 3 | 3.4 | 3 | 3.4 | 10.2 | 28,661 | ticks |
| 2024-10 | 3 | 3 | 3 | 3 | 10.2 | 31,758 | ticks |
| 2024-11 | 1 | 1 | 1 | 1.5 | 8.2 | 28,194 | ticks |
| 2024-12 | 1.14 | 1.21 | 1.14 | 1.21 | 7.2 | 28,729 | ticks |
| 2025-01 | 1.21 | 1.4 | 1.21 | 1.4 | 7.2 | 29,623 | ticks |
| 2025-02 | 1.12 | 1.16 | 1.12 | 1.16 | 7.2 | 27,220 | ticks |
| 2025-03 | 1.12 | 1.21 | 1.12 | 1.56 | 3.59 | 28,896 | ticks |
| 2025-04 | 1.12 | 1.21 | 1.12 | 1.21 | 2 | 28,591 | ticks |
| 2025-05 | 1.12 | 1.12 | 1.12 | 1.12 | 2 | 30,037 | ticks |
| 2025-06 | 1.12 | 1.3 | 1.12 | 1.3 | 4 | 28,746 | ticks |
| 2025-07 | 1.12 | 1.12 | 1.12 | 1.12 | 4.9 | 31,114 | ticks |
| 2025-08 | 1.12 | 1.12 | 1.12 | 1.12 | 5.9 | 28,817 | ticks |
| 2025-09 | 1.12 | 1.12 | 1.12 | 1.12 | 2 | 29,931 | ticks |
| 2025-10 | 1.12 | 1.12 | 1.12 | 1.12 | 2 | 31,500 | ticks |
| 2025-11 | 1.12 | 1.12 | 1.12 | 1.12 | 2 | 26,357 | ticks |
| 2025-12 | 1.12 | 1.21 | 1.12 | 1.21 | 2 | 29,843 | ticks |
| 2026-01 | 1.14 | 1.2 | 1.14 | 1.2 | 2 | 28,530 | ticks |
| 2026-02 | 1.14 | 1.14 | 1.14 | 1.14 | 1.95 | 27,209 | ticks |
| 2026-03 | 1.14 | 2 | 1.14 | 2 | 2 | 30,168 | ticks |
| 2026-04 | 1.36 | 1.36 | 1.36 | 1.36 | 2 | 29,725 | ticks |
| 2026-05 | 1.43 | 1.43 | 1.43 | 1.43 | 2 | 28,578 | ticks |
| 2026-06 | 1.43 | 1.43 | 1.43 | 1.43 | 2 | 29,916 | ticks |
| 2026-07 | 1.43 | 1.43 | 1.43 | 1.43 | 1.51 | 31,264 | ticks |
| 2026-08 | 1.43 | 1.43 | 1.43 | 1.43 | 2 | 28,876 | ticks |
| 2026-09 | 1.43 | 1.43 | 1.43 | 1.43 | 2 | 29,956 | ticks |
| 2026-10 | 1.43 | 1.43 | 1.43 | 1.43 | 2 | 2,743 | ticks |

### 2a. Spread by 30-minute bucket — current regime since 2026-05-14 (N = minutes)
Columns p50/p90/p99/mean refer to the per-minute time-weighted spread; `max_tick` is the single widest quote seen; `tick_*` = tick-weighted comparison. All-history versions (mixing all regimes) are in `audit/out/spread_buckets_*_all.csv`.

**New York time**
| bucket | N_min | p50 | p90 | p99 | max_tick | mean | tick_N | tick_p50 | tick_p99 |
|---|---|---|---|---|---|---|---|---|---|
| 00:00-00:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,037,814 | 1.43 | 1.43 |
| 00:30-00:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,019,247 | 1.43 | 1.43 |
| 01:00-01:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,137,819 | 1.43 | 1.43 |
| 01:30-01:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,165,238 | 1.43 | 1.43 |
| 02:00-02:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,186,065 | 1.43 | 1.43 |
| 02:30-02:59 | 3,059 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,014,120 | 1.43 | 1.43 |
| 03:00-03:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,211,177 | 1.43 | 1.43 |
| 03:30-03:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,090,535 | 1.43 | 1.43 |
| 04:00-04:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,277,777 | 1.43 | 1.43 |
| 04:30-04:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.71 | 1.43 | 1,115,797 | 1.43 | 1.43 |
| 05:00-05:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,073,819 | 1.43 | 1.43 |
| 05:30-05:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,022,037 | 1.43 | 1.43 |
| 06:00-06:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,014,477 | 1.43 | 1.43 |
| 06:30-06:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 995,267 | 1.43 | 1.43 |
| 07:00-07:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,148,058 | 1.43 | 1.43 |
| 07:30-07:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,132,214 | 1.43 | 1.43 |
| 08:00-08:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,235,168 | 1.43 | 1.43 |
| 08:30-08:59 | 3,060 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,328,079 | 1.43 | 1.43 |
| 09:00-09:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,409,392 | 1.43 | 1.43 |
| 09:30-09:59 | 3,060 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,727,751 | 1.43 | 1.43 |
| 10:00-10:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,712,431 | 1.43 | 1.43 |
| 10:30-10:59 | 3,052 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,688,793 | 1.43 | 1.43 |
| 11:00-11:29 | 3,039 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,667,690 | 1.43 | 1.43 |
| 11:30-11:59 | 3,050 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,646,878 | 1.43 | 1.43 |
| 12:00-12:29 | 3,057 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,612,556 | 1.43 | 1.43 |
| 12:30-12:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,586,994 | 1.43 | 1.43 |
| 13:00-13:29 | 2,942 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,546,108 | 1.43 | 1.43 |
| 13:30-13:59 | 2,940 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,529,324 | 1.43 | 1.43 |
| 14:00-14:29 | 2,940 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,533,610 | 1.43 | 1.43 |
| 14:30-14:59 | 2,940 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,525,047 | 1.43 | 1.43 |
| 15:00-15:29 | 2,940 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,543,475 | 1.43 | 1.43 |
| 15:30-15:59 | 2,940 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,591,469 | 1.43 | 1.43 |
| 16:00-16:29 | 2,940 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,111,942 | 1.43 | 1.43 |
| 16:30-16:59 | 2,687 | 1.43 | 1.43 | 1.43 | 1.43 | 1.42 | 696,997 | 1.43 | 1.43 |
| 18:00-18:29 | 2,550 | 1.43 | 1.43 | 1.43 | 2 | 1.41 | 601,067 | 1.43 | 1.43 |
| 18:30-18:59 | 3,058 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 612,816 | 1.43 | 1.43 |
| 19:00-19:29 | 3,021 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 622,165 | 1.43 | 1.43 |
| 19:30-19:59 | 3,027 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 861,877 | 1.43 | 1.43 |
| 20:00-20:29 | 3,030 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,439,717 | 1.43 | 1.43 |
| 20:30-20:59 | 3,030 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,334,881 | 1.43 | 1.43 |
| 21:00-21:29 | 3,030 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,384,882 | 1.43 | 1.43 |
| 21:30-21:59 | 3,030 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,347,457 | 1.43 | 1.43 |
| 22:00-22:29 | 3,030 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,238,380 | 1.43 | 1.43 |
| 22:30-22:59 | 3,030 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,121,042 | 1.43 | 1.43 |
| 23:00-23:29 | 3,030 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,065,240 | 1.43 | 1.43 |
| 23:30-23:59 | 3,030 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,119,066 | 1.43 | 1.43 |

**Server time** (note the clock moves relative to New York, see task 4)
| bucket | N_min | p50 | p90 | p99 | max_tick | mean | tick_N | tick_p50 | tick_p99 |
|---|---|---|---|---|---|---|---|---|---|
| 00:00-00:29 | 3,021 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 622,165 | 1.43 | 1.43 |
| 00:30-00:59 | 3,027 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 861,877 | 1.43 | 1.43 |
| 01:00-01:29 | 3,030 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,439,717 | 1.43 | 1.43 |
| 01:30-01:59 | 3,030 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,334,881 | 1.43 | 1.43 |
| 02:00-02:29 | 3,030 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,384,882 | 1.43 | 1.43 |
| 02:30-02:59 | 3,030 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,347,457 | 1.43 | 1.43 |
| 03:00-03:29 | 3,030 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,238,380 | 1.43 | 1.43 |
| 03:30-03:59 | 3,030 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,121,042 | 1.43 | 1.43 |
| 04:00-04:29 | 3,030 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,065,240 | 1.43 | 1.43 |
| 04:30-04:59 | 3,030 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,119,066 | 1.43 | 1.43 |
| 05:00-05:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,037,814 | 1.43 | 1.43 |
| 05:30-05:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,019,247 | 1.43 | 1.43 |
| 06:00-06:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,137,819 | 1.43 | 1.43 |
| 06:30-06:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,165,238 | 1.43 | 1.43 |
| 07:00-07:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,186,065 | 1.43 | 1.43 |
| 07:30-07:59 | 3,059 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,014,120 | 1.43 | 1.43 |
| 08:00-08:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,211,177 | 1.43 | 1.43 |
| 08:30-08:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,090,535 | 1.43 | 1.43 |
| 09:00-09:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,277,777 | 1.43 | 1.43 |
| 09:30-09:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.71 | 1.43 | 1,115,797 | 1.43 | 1.43 |
| 10:00-10:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,073,819 | 1.43 | 1.43 |
| 10:30-10:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,022,037 | 1.43 | 1.43 |
| 11:00-11:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,014,477 | 1.43 | 1.43 |
| 11:30-11:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 995,267 | 1.43 | 1.43 |
| 12:00-12:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,148,058 | 1.43 | 1.43 |
| 12:30-12:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,132,214 | 1.43 | 1.43 |
| 13:00-13:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,235,168 | 1.43 | 1.43 |
| 13:30-13:59 | 3,060 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,328,079 | 1.43 | 1.43 |
| 14:00-14:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,409,392 | 1.43 | 1.43 |
| 14:30-14:59 | 3,060 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 1,727,751 | 1.43 | 1.43 |
| 15:00-15:29 | 3,060 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,712,431 | 1.43 | 1.43 |
| 15:30-15:59 | 3,052 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,688,793 | 1.43 | 1.43 |
| 16:00-16:29 | 3,039 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,667,690 | 1.43 | 1.43 |
| 16:30-16:59 | 3,050 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,646,878 | 1.43 | 1.43 |
| 17:00-17:29 | 3,057 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,612,556 | 1.43 | 1.43 |
| 17:30-17:59 | 3,060 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,586,994 | 1.43 | 1.43 |
| 18:00-18:29 | 2,942 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,546,108 | 1.43 | 1.43 |
| 18:30-18:59 | 2,940 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,529,324 | 1.43 | 1.43 |
| 19:00-19:29 | 2,940 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,533,610 | 1.43 | 1.43 |
| 19:30-19:59 | 2,940 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,525,047 | 1.43 | 1.43 |
| 20:00-20:29 | 2,940 | 1.43 | 1.43 | 1.43 | 1.51 | 1.43 | 1,543,475 | 1.43 | 1.43 |
| 20:30-20:59 | 2,940 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,591,469 | 1.43 | 1.43 |
| 21:00-21:29 | 2,940 | 1.43 | 1.43 | 1.43 | 1.43 | 1.43 | 1,111,942 | 1.43 | 1.43 |
| 21:30-21:59 | 2,687 | 1.43 | 1.43 | 1.43 | 1.43 | 1.42 | 696,997 | 1.43 | 1.43 |
| 23:00-23:29 | 2,550 | 1.43 | 1.43 | 1.43 | 2 | 1.41 | 601,067 | 1.43 | 1.43 |
| 23:30-23:59 | 3,058 | 1.43 | 1.43 | 1.43 | 2 | 1.43 | 612,816 | 1.43 | 1.43 |

**All history, level-neutral (New York time).** Spread ÷ the day's own median, all regimes pooled, shows *when* spikes historically happened regardless of the level at the time (`s_max` = worst tick in the minute):
| bucket | N_min | p99 (s_med ratio) | p99.9 (s_max ratio) | max (s_max ratio) | share s_max > 2x % | share s_max > 4x % |
|---|---|---|---|---|---|---|
| 00:00-00:29 | 39,653 | 1.21 | 3.5 | 8.58 | 0.89 | 0.07 |
| 00:30-00:59 | 39,646 | 1.21 | 3.86 | 9 | 0.94 | 0.08 |
| 01:00-01:29 | 39,654 | 1.3 | 3.87 | 12.75 | 1.37 | 0.09 |
| 01:30-01:59 | 39,619 | 1.43 | 3.86 | 12 | 1.54 | 0.09 |
| 02:00-02:29 | 39,611 | 1.44 | 5.37 | 15.75 | 2.62 | 0.25 |
| 02:30-02:59 | 39,638 | 1.3 | 5.17 | 11.92 | 2.48 | 0.25 |
| 03:00-03:29 | 39,630 | 1.26 | 5.02 | 20.33 | 2.52 | 0.24 |
| 03:30-03:59 | 39,613 | 1.22 | 5.17 | 17.83 | 2.14 | 0.25 |
| 04:00-04:29 | 39,656 | 1.19 | 4.21 | 8.5 | 1.48 | 0.11 |
| 04:30-04:59 | 39,669 | 1.13 | 3.77 | 6.65 | 1.12 | 0.07 |
| 05:00-05:29 | 39,649 | 1.17 | 3.8 | 7.07 | 1.19 | 0.07 |
| 05:30-05:59 | 39,664 | 1.15 | 3.86 | 13.17 | 1.09 | 0.08 |
| 06:00-06:29 | 39,655 | 1.14 | 4.21 | 8.42 | 1.04 | 0.11 |
| 06:30-06:59 | 39,648 | 1.19 | 3.86 | 8.42 | 1.19 | 0.09 |
| 07:00-07:29 | 39,654 | 1.2 | 4.21 | 14 | 1.29 | 0.12 |
| 07:30-07:59 | 39,683 | 1.21 | 4.57 | 14.57 | 1.31 | 0.17 |
| 08:00-08:29 | 39,681 | 1.25 | 10.05 | 55.29 | 2.01 | 0.56 |
| 08:30-08:59 | 39,694 | 1.71 | 15.68 | 99 | 4.04 | 1.13 |
| 09:00-09:29 | 39,726 | 1.19 | 4.57 | 15.29 | 1.77 | 0.27 |
| 09:30-09:59 | 39,657 | 1.79 | 8.88 | 25.29 | 4.13 | 0.76 |
| 10:00-10:29 | 39,672 | 1.57 | 9.69 | 18.86 | 2.54 | 0.45 |
| 10:30-10:59 | 39,674 | 1.41 | 4.33 | 13.14 | 1.33 | 0.12 |
| 11:00-11:29 | 39,592 | 1.34 | 3.86 | 11.14 | 1.01 | 0.07 |
| 11:30-11:59 | 39,661 | 1.3 | 3.86 | 19.5 | 0.96 | 0.08 |
| 12:00-12:29 | 39,700 | 1.21 | 3.5 | 11.83 | 0.63 | 0.04 |
| 12:30-12:59 | 39,691 | 1.18 | 3.86 | 21.92 | 0.71 | 0.08 |
| 13:00-13:29 | 38,436 | 1.19 | 3.86 | 19.42 | 0.73 | 0.09 |
| 13:30-13:59 | 38,291 | 1.17 | 3.9 | 13.5 | 0.71 | 0.1 |
| 14:00-14:29 | 38,294 | 1.28 | 5.17 | 92.43 | 1.27 | 0.21 |
| 14:30-14:59 | 38,286 | 1.23 | 4.57 | 11.83 | 1.1 | 0.18 |
| 15:00-15:29 | 38,030 | 1.26 | 4.33 | 14 | 1.05 | 0.12 |
| 15:30-15:59 | 37,675 | 1.39 | 6.03 | 13.21 | 1.45 | 0.25 |
| 16:00-16:29 | 24,819 | 1.33 | 7.28 | 13.86 | 2.35 | 0.51 |
| 16:30-16:59 | 25,487 | 1.67 | 5.5 | 23.93 | 2.67 | 0.48 |
| 17:00-17:29 | 1 | 1 | 1 | 1 | 0 | 0 |
| 17:30-17:59 | 3 | 1.43 | 1.44 | 1.44 | 0 | 0 |
| 18:00-18:29 | 26,858 | 1.8 | 8.2 | 27.36 | 5.08 | 1.05 |
| 18:30-18:59 | 39,209 | 1.3 | 4.75 | 12.25 | 1.2 | 0.19 |
| 19:00-19:29 | 39,465 | 1.25 | 4.29 | 13.17 | 0.91 | 0.11 |
| 19:30-19:59 | 39,428 | 1.23 | 4.33 | 8.83 | 1.07 | 0.12 |
| 20:00-20:29 | 39,600 | 1.25 | 4.94 | 13.58 | 1.64 | 0.13 |
| 20:30-20:59 | 39,564 | 1.25 | 4.14 | 12 | 1.33 | 0.1 |
| 21:00-21:29 | 39,552 | 1.25 | 3.9 | 11.92 | 1.49 | 0.1 |
| 21:30-21:59 | 39,552 | 1.25 | 4.57 | 11.5 | 1.59 | 0.14 |
| 22:00-22:29 | 39,593 | 1.25 | 4.33 | 10.25 | 1.33 | 0.13 |
| 22:30-22:59 | 39,654 | 1.21 | 3.61 | 7.25 | 1.24 | 0.08 |
| 23:00-23:29 | 39,643 | 1.22 | 3.86 | 9.67 | 1.13 | 0.1 |
| 23:30-23:59 | 39,659 | 1.21 | 3.65 | 10.25 | 0.94 | 0.09 |

### 2b. Daily rollover / re-open
The only spread spike near the daily break is at the **re-open after the break**, not before it. Spike minute: **18:00 ET** (mean max-spread ratio 1.79× the day's median at the re-open minute, all history) — INFERRED rollover time. Re-open times by day count (ET): 18:00: 487, 18:30: 277, 18:05: 260, 18:31: 9, 18:02: 8. The MT5 swap rollover time itself cannot be read from the API (see questions). The window before the re-open is the closed break, so only −30..−1 relative to the *last bar before the break* has data on that side.

Window around the **re-open** (rel. minute 0 = first bar after the break; ratio = spread ÷ that day's median; `*_cur` = current regime, index points):
| rel_min | N_all | ratio_med_all | ratio_p99_all | ratio_max_all | N_cur | p50_cur | p99_cur | max_cur |
|---|---|---|---|---|---|---|---|---|
| 0 | 1,063.0 | 1 | 5.97 | 11.86 | 81 | 1.36 | 1.36 | 1.36 |
| 1 | 1,049.0 | 1 | 5.17 | 11.86 | 81 | 1.36 | 1.49 | 2 |
| 2 | 1,060.0 | 1 | 3.5 | 11.86 | 81 | 1.43 | 1.54 | 2 |
| 3 | 1,059.0 | 1 | 3.5 | 6.5 | 81 | 1.43 | 1.43 | 1.43 |
| 4 | 1,059.0 | 1 | 3 | 6.3 | 81 | 1.43 | 1.43 | 2 |
| 5 | 1,059.0 | 1 | 3.48 | 4.57 | 81 | 1.43 | 1.43 | 2 |
| 6 | 1,059.0 | 1 | 3 | 4.57 | 81 | 1.43 | 1.54 | 2 |
| 7 | 1,059.0 | 1 | 2.94 | 4.57 | 81 | 1.43 | 1.54 | 2 |
| 8 | 1,060.0 | 1 | 2.9 | 4.93 | 81 | 1.43 | 1.43 | 1.43 |
| 9 | 1,060.0 | 1 | 2.5 | 5.17 | 81 | 1.43 | 1.54 | 2 |
| 10 | 1,060.0 | 1 | 2.67 | 4.67 | 81 | 1.43 | 1.43 | 1.43 |
| 11 | 1,060.0 | 1 | 2.65 | 4.14 | 81 | 1.43 | 1.43 | 1.43 |
| 12 | 1,060.0 | 1 | 2.67 | 3.56 | 81 | 1.43 | 1.43 | 2 |
| 13 | 1,060.0 | 1 | 2.8 | 4.33 | 81 | 1.43 | 2 | 2 |
| 14 | 1,059.0 | 1 | 2.57 | 4.67 | 81 | 1.43 | 1.43 | 1.43 |
| 15 | 1,060.0 | 1 | 2.67 | 5.08 | 81 | 1.43 | 1.54 | 2 |
| 16 | 1,059.0 | 1 | 1.92 | 5.5 | 81 | 1.43 | 1.43 | 2 |
| 17 | 1,060.0 | 1 | 2.01 | 5.92 | 81 | 1.43 | 1.54 | 2 |
| 18 | 1,060.0 | 1 | 2.5 | 3.5 | 81 | 1.43 | 1.43 | 1.43 |
| 19 | 1,060.0 | 1 | 2.01 | 3.5 | 81 | 1.43 | 1.43 | 1.43 |
| 20 | 1,060.0 | 1 | 2.14 | 5.5 | 81 | 1.43 | 1.43 | 1.43 |
| 21 | 1,060.0 | 1 | 2.06 | 3.5 | 81 | 1.43 | 1.43 | 1.43 |
| 22 | 1,059.0 | 1 | 1.83 | 4.5 | 81 | 1.43 | 1.43 | 1.43 |
| 23 | 1,058.0 | 1 | 1.84 | 3.14 | 81 | 1.43 | 1.43 | 1.43 |
| 24 | 1,059.0 | 1 | 1.85 | 3.83 | 81 | 1.43 | 1.43 | 1.43 |
| 25 | 1,058.0 | 1 | 1.98 | 3.5 | 81 | 1.43 | 1.43 | 1.43 |
| 26 | 1,057.0 | 1 | 2 | 3.5 | 81 | 1.43 | 1.43 | 1.43 |
| 27 | 1,060.0 | 1 | 1.83 | 3.77 | 81 | 1.43 | 1.43 | 1.43 |
| 28 | 1,059.0 | 1 | 2 | 3.77 | 81 | 1.43 | 1.43 | 1.43 |
| 29 | 1,060.0 | 1 | 1.95 | 5.5 | 81 | 1.43 | 1.43 | 1.43 |
| 30 | 1,061.0 | 1 | 1.85 | 3.86 | 81 | 1.43 | 1.43 | 1.43 |

Window before the break (rel. minute 0 = last bar before the break):
| rel_min | N_all | ratio_med_all | ratio_p99_all | ratio_max_all | N_cur | p50_cur | p99_cur | max_cur |
|---|---|---|---|---|---|---|---|---|
| -30 | 1,129.0 | 1 | 2.86 | 8.86 | 98 | 1.43 | 1.43 | 1.43 |
| -29 | 1,130.0 | 1 | 2.31 | 8.2 | 98 | 1.43 | 1.43 | 1.43 |
| -28 | 1,277.0 | 1 | 3.42 | 23.93 | 98 | 1.43 | 1.43 | 1.43 |
| -27 | 1,277.0 | 1 | 3.42 | 8.2 | 98 | 1.43 | 1.43 | 1.43 |
| -26 | 1,277.0 | 1 | 3.18 | 6.83 | 98 | 1.43 | 1.43 | 1.43 |
| -25 | 1,277.0 | 1 | 2.83 | 8.5 | 98 | 1.43 | 1.43 | 1.43 |
| -24 | 1,277.0 | 1 | 3.11 | 6.5 | 98 | 1.43 | 1.43 | 1.43 |
| -23 | 1,277.0 | 1 | 3.25 | 7.43 | 98 | 1.43 | 1.43 | 1.43 |
| -22 | 1,277.0 | 1 | 3.14 | 5.4 | 98 | 1.43 | 1.43 | 1.43 |
| -21 | 1,277.0 | 1 | 2.74 | 7.5 | 98 | 1.43 | 1.43 | 1.43 |
| -20 | 1,277.0 | 1 | 2.68 | 5.17 | 98 | 1.43 | 1.43 | 1.43 |
| -19 | 1,277.0 | 1 | 2.67 | 5.5 | 98 | 1.43 | 1.43 | 1.43 |
| -18 | 1,277.0 | 1 | 3.15 | 10.29 | 98 | 1.43 | 1.43 | 1.43 |
| -17 | 1,277.0 | 1 | 2.78 | 5.5 | 98 | 1.43 | 1.43 | 1.43 |
| -16 | 1,277.0 | 1 | 2.67 | 7.8 | 98 | 1.43 | 1.43 | 1.43 |
| -15 | 1,276.0 | 1 | 3.33 | 8.86 | 98 | 1.43 | 1.43 | 1.43 |
| -14 | 1,277.0 | 1 | 3.22 | 4.82 | 98 | 1.43 | 1.43 | 1.43 |
| -13 | 1,277.0 | 1 | 3.02 | 8.2 | 98 | 1.43 | 1.43 | 1.43 |
| -12 | 1,276.0 | 1 | 3.5 | 6 | 98 | 1.43 | 1.43 | 1.43 |
| -11 | 1,277.0 | 1 | 2.67 | 5.5 | 98 | 1.43 | 1.43 | 1.43 |
| -10 | 1,274.0 | 1 | 2.83 | 5.05 | 98 | 1.43 | 1.43 | 1.43 |
| -9 | 1,274.0 | 1 | 3.14 | 4.62 | 98 | 1.43 | 1.43 | 1.43 |
| -8 | 1,276.0 | 1 | 4.14 | 8.86 | 98 | 1.43 | 1.43 | 1.43 |
| -7 | 1,276.0 | 1 | 3.21 | 4.33 | 98 | 1.43 | 1.43 | 1.43 |
| -6 | 1,277.0 | 1 | 3.42 | 4.82 | 98 | 1.43 | 1.43 | 1.43 |
| -5 | 1,277.0 | 1 | 3.14 | 6.3 | 98 | 1.43 | 1.43 | 1.43 |
| -4 | 1,276.0 | 1 | 3.3 | 7.1 | 98 | 1.43 | 1.43 | 1.43 |
| -3 | 1,276.0 | 1 | 3.31 | 5.3 | 98 | 1.43 | 1.43 | 1.43 |
| -2 | 1,276.0 | 1 | 3.3 | 4.17 | 98 | 1.36 | 1.43 | 1.43 |
| -1 | 1,277.0 | 1 | 3.57 | 7.29 | 98 | 1.36 | 1.43 | 1.43 |
| 0 | 1,282.0 | 1 | 4.38 | 5.53 | 98 | 1.36 | 1.43 | 1.43 |

### 2c. Event windows (APPROXIMATE — no events file was given)

**08:30 ET (US data releases)** — APPROXIMATE: empirical, peak range in [0,+2] min >= 4.0x the median of [-45,-15); control false-positive rate 2.4%. Event days 499 (of which with tick data 397, in the current regime 21); non-event days 1287. Detected event days per year: 2019: 22, 2020: 45, 2021: 56, 2022: 79, 2023: 102, 2024: 95, 2025: 61, 2026: 39. NOTE: event days are *defined* by range, so the range comparison is circular by construction; the spread comparison is not (spread was not used for detection). Spread ratio = spread ÷ day median (removes regime level). **Reliability: only 21 event days fall in the current regime, so current-regime event spread numbers (`*_cur`) are not reliable for p99.** 
| window (min) | range_med_event | range_med_non | range_x | spread_ratio_med_event | spread_ratio_med_non | spread_ratio_p99_event | spread_ratio_p99_non | spread_max_event | spread_max_non | spread_max_event_cur | spread_max_non_cur |
|---|---|---|---|---|---|---|---|---|---|---|---|
| -15..-1 | 4.55 | 4.5 | 1.01 | 1 | 1 | 5.17 | 1.34 | 38.7 | 11.6 | 1.43 | 1.43 |
| 0 | 34.85 | 6.7 | 5.2 | 1 | 1 | 8.92 | 1.41 | 69.3 | 11.25 | 2 | 1.43 |
| +1..+2 | 16.12 | 5.74 | 2.81 | 1 | 1 | 3.84 | 1.27 | 29 | 10.2 | 1.43 | 1.43 |
| +3..+5 | 11.38 | 5.25 | 2.17 | 1 | 1 | 3.14 | 1.21 | 15.2 | 10.2 | 2 | 1.43 |
| +6..+15 | 8.51 | 4.96 | 1.71 | 1 | 1 | 1.8 | 1.21 | 11 | 11.6 | 1.43 | 1.43 |
| +16..+30 | 7.13 | 4.7 | 1.52 | 1 | 1 | 1.44 | 1.18 | 10.2 | 10.7 | 1.43 | 1.43 |

**14:00 ET (FOMC / Fed)** — APPROXIMATE: empirical, peak range in [0,+2] min >= 4.0x the median of [-45,-15); control false-positive rate 1.3%. Event days 119 (of which with tick data 79, in the current regime 6); non-event days 1674. Detected event days per year: 2019: 13, 2020: 15, 2021: 20, 2022: 18, 2023: 16, 2024: 15, 2025: 13, 2026: 9. NOTE: event days are *defined* by range, so the range comparison is circular by construction; the spread comparison is not (spread was not used for detection). Spread ratio = spread ÷ day median (removes regime level). **Reliability: only 6 event days fall in the current regime, so current-regime event spread numbers (`*_cur`) are not reliable for p99.** Tick-era event days: 79.
| window (min) | range_med_event | range_med_non | range_x | spread_ratio_med_event | spread_ratio_med_non | spread_ratio_p99_event | spread_ratio_p99_non | spread_max_event | spread_max_non | spread_max_event_cur | spread_max_non_cur |
|---|---|---|---|---|---|---|---|---|---|---|---|
| -15..-1 | 5.36 | 6.62 | 0.81 | 1 | 1 | 3.03 | 1.2 | 11.05 | 10.6 | 1.43 | 1.51 |
| 0 | 34.3 | 8.91 | 3.85 | 1 | 1 | 5.13 | 1.22 | 64.7 | 10.2 | 1.43 | 1.43 |
| +1..+2 | 21.37 | 7.87 | 2.71 | 1 | 1 | 4 | 1.23 | 10.85 | 10.2 | 1.43 | 1.43 |
| +3..+5 | 15.75 | 7.17 | 2.2 | 1 | 1 | 2.89 | 1.21 | 9.8 | 8.65 | 1.43 | 1.43 |
| +6..+15 | 11.56 | 7 | 1.65 | 1 | 1 | 2.37 | 1.21 | 10.2 | 10.2 | 1.43 | 1.43 |
| +16..+30 | 9.02 | 6.75 | 1.34 | 1 | 1 | 1.75 | 1.17 | 10.2 | 10.2 | 1.43 | 1.43 |

Full per-minute tables (−15..+30): `audit/out/events_*.csv`.

### 2e. Share of minutes with spread above k × the day's median
| sample | N_min | s_med>2x | s_med>4x | s_med>8x | s_max>2x | s_max>4x | s_max>8x |
|---|---|---|---|---|---|---|---|
| 2021 | 123,339 | 0.2416% | 0.0049% | 0.0000% | 0.5521% | 0.0073% | 0.0000% |
| 2022 | 340,322 | 0.2577% | 0.0356% | 0.0073% | 4.5624% | 0.6823% | 0.1381% |
| 2023 | 336,658 | 0.2100% | 0.0068% | 0.0003% | 1.5529% | 0.2424% | 0.0457% |
| 2024 | 354,230 | 0.1098% | 0.0000% | 0.0000% | 1.7048% | 0.1225% | 0.0056% |
| 2025 | 350,675 | 0.0262% | 0.0103% | 0.0000% | 0.0650% | 0.0220% | 0.0000% |
| 2026 | 266,965 | 0.0000% | 0.0000% | 0.0000% | 0.0000% | 0.0000% | 0.0000% |
| ALL | 1,772,189 | 0.1333% | 0.0105% | 0.0015% | 1.5632% | 0.2064% | 0.0363% |
| current regime (since 2026-05-14) | 138,682 | 0.0000% | 0.0000% | 0.0000% | 0.0000% | 0.0000% | 0.0000% |
| ALL, cash session 09:30-16:00 ET only | 506,659 | 0.0665% | 0.0030% | 0.0008% | 1.3611% | 0.1978% | 0.0420% |

### Bar `spread` field vs tick-derived spread (bias of the bar field)
The bar `spread` is one snapshot per bar. Over the overlap (index points = column ÷ 100 in `point` units):
| tick-derived reference | N | bar == ref % | mean(bar-ref) idx pts | median idx pts | p01 idx pts | p99 idx pts |
|---|---|---|---|---|---|---|
| spread at minute open (carried-in quote) | 1,769,318 | 91.99 | -0.0159 | 0 | -0.5 | 0 |
| spread at last tick of the minute | 1,772,189 | 93.35 | -0.0159 | 0 | -0.5 | 0 |
| time-weighted median in the minute | 1,772,189 | 91.68 | -0.0126 | 0 | -0.45 | 0 |
| minimum in the minute | 1,772,189 | 99.75 | -0.0001 | 0 | 0 | 0 |
| maximum in the minute | 1,772,189 | 82.85 | -0.1143 | 0 | -2 | 0 |
→ The bar spread equals the **minimum** tick spread inside the minute in ~99.7% of bars. It understates typical spread slightly and understates spikes completely. Do not use it for p99 or event statistics.

## 6. Task 3 — Swap and financing
`swap_mode` = **DISABLED** (0), `swap_long` = -428.93, `swap_short` = 0.0, triple-swap weekday = **Friday** (`swap_rollover3days` = 5).
**The terminal says swap is disabled while populated values exist.** This is not specific to this symbol:
| group | swap_mode | symbols | with_nonzero_swap_values |
|---|---|---|---|
| Crypto | DISABLED | 15 | 15 |
| Forex Major | DISABLED | 11 | 11 |
| Forex Major | POINTS | 1 | 1 |
| Forex Minor | DISABLED | 9 | 9 |
| Forex Minor | POINTS | 9 | 9 |
| Index | DISABLED | 9 | 9 |
| Index | POINTS | 1 | 1 |
| Metals&Energies | DISABLED | 3 | 3 |
| Metals&Energies | POINTS | 5 | 5 |
| Stock | POINTS | 57 | 57 |
| Thematic Indices | POINTS | 5 | 5 |

Formulas (per 1.0 lot, price 30,903.6; negative = the trader pays). Only the 'points' reading gives a financing rate in a sensible range:
| reading of the numbers | formula | long pts/night | short pts/night | long % p.a. | short % p.a. | plausible? |
|---|---|---|---|---|---|---|
| POINTS | swap x point | -4.2893 | 0 | -5.066 | 0 | yes |
| CURRENCY_DEPOSIT (USD per lot per night) | swap / (tick_value/tick_size) | -428.93 | 0 | -506.61 | 0 | no - absurd financing rate |
| INTEREST_CURRENT (annual % of price) | price x swap/100 / 365 | -363.16 | 0 | -428.93 | 0 | no - absurd financing rate |

**Reading used: POINTS (INFERRED)** → index points per night: long **-4.2893**, short **0.0** (= swap × point). Annualised: long -5.066% of price, short 0.0% (= pts × 365 / price). Short also pays: **no**; short receives: no. Charged per rollover; the Friday rollover counts 3× → 7 night-equivalents per week.

Evidence from this account's deals (positions that crossed ≥1 server midnight). Expected charge under the 'points' reading is far below the 0.01 rounding of the booked swap, so this is **inconclusive**:
| symbol | direction | lots | nights | swap_booked | expected_if_points |
|---|---|---|---|---|---|
| XAUUSD. | long | 0.01 | 1 | 0 | -0.4034 |
| XAUUSD. | long | 0.01 | 1 | 0 | -0.4034 |

**Whether swap is actually charged on this account is UNKNOWN.** Modelled conservatively as charged at the 'points' reading (long); if the account is swap-free, swap = 0.
The rollover time cannot be read from the API. INFERRED from the spread spike: the market re-opens at the time shown in 2b; the usual MT5 default (server midnight) would be 19:00 ET in the London-clock era. Please confirm in the terminal (see questions).

## 7. Task 4 — Server time ↔ UTC ↔ New York
**Live offset (MEASURED):** latest tick time − UTC now = 3600.2 s → **server = UTC+1h** (residual 0.2 s = tick age; market live = True). PC clock checked against an HTTP time source (1 s resolution): skew -0.02 s.

**Server clock history (MEASURED weekly, then segmented).** The 09:30 ET cash-open step in 1-min range was detected for 377 weeks (367 informative). The 08:30 ET release spike sits exactly 60 min before the open in 56.1% of weeks (median -60.0 min), which is consistent with a single clock for both events.
| era_start_week | era_end_week | weeks | convention | weeks_matching | weeks_informative | match_pct |
|---|---|---|---|---|---|---|
| 2019-07-15 | 2021-10-25 | 120 | UTC fixed (UTC+0) | 118 | 118 | 100.00 |
| 2021-11-01 | 2026-09-28 | 257 | London (UTC+0/+1, EU DST) | 244 | 249 | 98 |

Match of each candidate convention against the weekly observation:
|  | match_pct_all_weeks | weeks |
|---|---|---|
| UTC fixed (UTC+0) | 59.9 | 367 |
| London (UTC+0/+1, EU DST) | 78.5 | 367 |
| ET+5 (UTC+0/+1, US DST) | 71.7 | 367 |
| Fixed UTC+1 | 39.2 | 367 |
| EET (UTC+2/+3, EU DST) | 0 | 367 |
| NY-close ET+7 (UTC+2/+3, US DST) | 0 | 367 |
| Fixed UTC+2 | 0 | 367 |
| Fixed UTC+3 | 0 | 367 |

**The 'NY close' convention (UTC+2/+3, 09:30 ET = 16:30 server) matches 0.0% of weeks — it is not what this server does.** Mismatch weeks (US and EU DST differ) decide US-linked vs EU-linked: in the current era 18 of 18 match the EU (London) rule and 0 match a US-linked rule.

**Offset regimes by run of weeks** (informative weeks; offset = server − UTC in hours; the full weekly table with the detected cash-open, release-spike and unconstrained-peak minutes is `audit/out/server_time_weekly.csv`):
| first_week | last_week | weeks | offset_h | open_0930ET_server | release_spike_server_secondary |
|---|---|---|---|---|---|
| 2019-07-22 | 2022-03-21 | 139 | 0 | 13:30/14:30 | 12:30 |
| 2022-03-28 | 2022-10-24 | 30 | 1 | 14:30 | 13:30 |
| 2022-10-31 | 2023-02-06 | 15 | 0 | 13:30/14:30 | 13:30 |
| 2023-02-13 | 2023-02-13 | 1 | -1 | 13:30 | 11:04 |
| 2023-02-20 | 2023-03-20 | 5 | 0 | 13:30/14:30 | 13:30 |
| 2023-03-27 | 2023-04-03 | 2 | 1 | 14:30 | 13:15 |
| 2023-04-10 | 2023-04-10 | 1 | 0 | 13:30 | 11:14 |
| 2023-04-17 | 2023-10-23 | 28 | 1 | 14:30 | 13:30 |
| 2023-10-30 | 2024-02-05 | 12 | 0 | 13:30/14:30 | 13:30 |
| 2024-02-12 | 2024-02-12 | 1 | -1 | 13:30 | 12:01 |
| 2024-02-19 | 2024-03-25 | 6 | 0 | 13:30/14:30 | 12:30 |
| 2024-04-01 | 2024-05-06 | 6 | 1 | 14:30 | 13:30 |
| 2024-05-13 | 2024-05-13 | 1 | 0 | 13:30 | 12:30 |
| 2024-05-20 | 2024-10-21 | 21 | 1 | 14:30 | 13:30 |
| 2024-10-28 | 2025-02-03 | 13 | 0 | 13:30/14:30 | 13:30 |
| 2025-02-10 | 2025-02-10 | 1 | -1 | 13:30 | 11:00 |
| 2025-02-17 | 2025-03-24 | 6 | 0 | 13:30/14:30 | 12:30 |
| 2025-03-31 | 2025-10-20 | 30 | 1 | 14:30 | 13:30 |
| 2025-10-27 | 2026-03-23 | 22 | 0 | 13:30/14:30 | 13:30 |
| 2026-03-30 | 2026-09-28 | 27 | 1 | 14:30 | 12:00 |

The 5 one-week runs (offset −1, or a single 0 inside a summer run) contradict both neighbouring runs and carry implausible release-spike minutes: treat them as detection noise (weeks where the open step was not the dominant step), not clock changes. The release-spike column is a secondary, noisy detector (it picks the strongest recurring spike in the window before the open) and agrees with 'open − 60 min' in only 56.1% of weeks; the 18 mismatch-week observations and the 98% match of the London rule do not depend on it.

Weeks where US and EU DST differ — observed offset vs what each convention predicts (hours, server − UTC):
| week | obs_offset_h | margin | open_hhmm | UTC fixed | London | ET+5 | NY-close ET+7 | EET |
|---|---|---|---|---|---|---|---|---|
| 2019-10-28 | 0 | 1.29 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2020-03-09 | 0 | 2.15 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2020-03-16 | 0 | 2.23 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2020-03-23 | 0 | 2.24 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2020-10-26 | 0 | 2.58 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2021-03-15 | 0 | 3.26 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2021-03-22 | 0 | 2.35 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2021-11-01 | 0 | 5.22 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2022-03-14 | 0 | 2.17 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2022-03-21 | 0 | 2.55 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2022-10-31 | 0 | 2.39 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2023-03-13 | 0 | 1.45 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2023-03-20 | 0 | 2.58 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2023-10-30 | 0 | 1.19 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2024-03-11 | 0 | 1.41 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2024-03-18 | 0 | 2.05 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2024-03-25 | 0 | 1.63 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2024-10-28 | 0 | 2.48 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2025-03-10 | 0 | 2.88 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2025-03-17 | 0 | 1.61 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2025-03-24 | 0 | 1.62 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2025-10-27 | 0 | 1.87 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2026-03-09 | 0 | 1.76 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2026-03-16 | 0 | 1.51 | 13:30 | 0 | 0 | 1 | 3 | 2 |
| 2026-03-23 | 0 | 1.81 | 13:30 | 0 | 0 | 1 | 3 | 2 |

The era boundary is only identifiable up to the winter ambiguity: UTC-fixed and London time are identical from the end of October to the end of March, so the switch lies between the last UTC-fixed summer week and the first London summer week; any date in that winter gives identical conversions. 09:30 ET therefore sits at **14:30 server in normal weeks and 13:30 server in the 2–3 mismatch weeks each March and 1 week each Oct/Nov** (London era).

Helper: `audit.tz.ServerClock` (eras + rules `fixed` / `ny` / `eu`), saved as `audit/out/server_clock.json`; `to_utc`, `to_et`, `utc_to_server`, `et_to_server`. Tests: `python -m pytest audit/tests -q` (DST transitions, US/EU mismatch weeks, round trips, era switch).

## 8. Task 5 — Data integrity
**M1 bars (MEASURED):**
| item | value | note |
|---|---|---|
| bars | 2,471,212 |  |
| duplicate_timestamps | 0 |  |
| non_monotonic_timestamps | 0 |  |
| nan_prices | 0 |  |
| nonpositive_prices | 0 |  |
| high<low | 0 |  |
| high<max(open,close) | 0 |  |
| low>min(open,close) | 0 |  |
| zero_range_bars (high==low) | 527 |  |
| zero_range_pct | 0.021 |  |
| bar_spread==0 | 699,489 |  |
| bar_spread<0 | 0 |  |
| tick_volume==0 | 0 |  |
| real_volume_nonzero | 0 |  |
| year | bars | zero_range_pct | bar_spread_zero_pct |
|---|---|---|---|
| 2019 | 156,827 | 0.04 | 100.00 |
| 2020 | 334,642 | 0.01 | 100.00 |
| 2021 | 329,875 | 0.05 | 62.91 |
| 2022 | 340,334 | 0.01 | 0.15 |
| 2023 | 336,658 | 0.04 | 0 |
| 2024 | 354,286 | 0.01 | 0 |
| 2025 | 350,730 | 0.01 | 0 |
| 2026 | 267,860 | 0 | 0 |

**Ticks (MEASURED, all days):**
| check | count | share_of_ticks_% | handling |
|---|---|---|---|
| ticks | 237,946,841 | 100.00 |  |
| time_msc going backwards | 0 | 0 | sorted before use |
| exact duplicate ticks (time, bid, ask, flags) | 0 | 0 |  |
| bid<=0 or ask<=0 | 0 | 0 | ignored for spread |
| crossed quotes (bid > ask) | 1 | 0 | excluded from spread stats |
| zero spread (bid == ask) | 2,042 | 0.001 | kept |
| last != 0 | 0 | 0 |  |
| volume != 0 | 0 | 0 |  |

**Stale quotes** (consecutive bars with no price change at all). Runs by minimum length:
| >=5 min | >=15 min | >=30 min | >=60 min |
|---|---|---|---|
| 0 | 0 | 0 | 0 |
Longest runs:
| start_server | start_et | minutes |
|---|---|---|
| 2019-07-30 22:39 | 2019-07-30 18:39 | 3 |
| 2023-07-04 23:35 | 2023-07-04 18:35 | 3 |
| 2023-07-25 00:28 | 2023-07-24 19:28 | 3 |
| 2019-07-25 04:57 | 2019-07-25 00:57 | 2 |
| 2019-08-20 20:15 | 2019-08-20 16:15 | 2 |
| 2019-10-27 22:55 | 2019-10-27 18:55 | 2 |
| 2019-10-31 23:27 | 2019-10-31 19:27 | 2 |
| 2019-11-28 13:08 | 2019-11-28 08:08 | 2 |
| 2019-12-06 04:46 | 2019-12-05 23:46 | 2 |
| 2019-12-31 06:02 | 2019-12-31 01:02 | 2 |

**Outlier returns |ret| > 8× local sigma (past-only, 120-bar window)**: 1,339 of 2,468,207 tested 1-min returns (0.054%), 45.5% inside the 08:30/09:30/10:00/14:00 ET news windows. Heavy tails, not necessarily errors. By year:
| year | outliers | tested_returns | per_100k |
|---|---|---|---|
| 2019 | 160 | 156,333 | 102.30 |
| 2020 | 187 | 334,177 | 56 |
| 2021 | 157 | 329,534 | 47.6 |
| 2022 | 187 | 339,877 | 55 |
| 2023 | 163 | 336,304 | 48.5 |
| 2024 | 170 | 353,963 | 48 |
| 2025 | 185 | 350,399 | 52.8 |
| 2026 | 130 | 267,620 | 48.6 |
Largest 30 (full list: `audit/out/outliers_top.csv`):
| server | et | move_pts | sigma_pts | z | tick_volume | in_news_window |
|---|---|---|---|---|---|---|
| 2022-10-13 13:30 | 2022-10-13 08:30 | -381.40 | 3.87 | 98.7 | 56 | True |
| 2022-11-10 13:30 | 2022-11-10 08:30 | 289.60 | 3.13 | 92.4 | 198 | True |
| 2025-02-12 13:30 | 2025-02-12 08:30 | -226.20 | 2.76 | 81.9 | 124 | True |
| 2022-12-02 13:30 | 2022-12-02 08:30 | -229.00 | 2.8 | 81.8 | 245 | True |
| 2023-11-14 13:30 | 2023-11-14 08:30 | 152.00 | 1.9 | 79.9 | 73 | True |
| 2022-12-09 13:30 | 2022-12-09 08:30 | -176.90 | 2.41 | 73.5 | 166 | True |
| 2024-04-10 13:30 | 2024-04-10 08:30 | -235.00 | 3.37 | 69.8 | 192 | True |
| 2022-09-13 13:30 | 2022-09-13 08:30 | -262.60 | 3.91 | 67.2 | 204 | True |
| 2023-01-12 13:29 | 2023-01-12 08:29 | -131.00 | 2.17 | 60.3 | 164 | True |
| 2025-10-24 13:30 | 2025-10-24 08:30 | 132.30 | 2.42 | 54.7 | 267 | True |
| 2024-05-15 13:30 | 2024-05-15 08:30 | 118.90 | 2.25 | 52.9 | 171 | True |
| 2025-05-12 08:00 | 2025-05-12 03:00 | 183.60 | 3.53 | 52 | 382 | False |
| 2023-04-12 13:30 | 2023-04-12 08:30 | 127.90 | 2.53 | 50.6 | 261 | True |
| 2024-05-03 13:30 | 2024-05-03 08:30 | 133.70 | 2.69 | 49.7 | 164 | True |
| 2023-10-06 13:30 | 2023-10-06 08:30 | -153.60 | 3.14 | 49 | 179 | True |
| 2024-06-12 13:30 | 2024-06-12 08:30 | 129.20 | 2.69 | 47.9 | 154 | True |
| 2024-07-11 13:30 | 2024-07-11 08:30 | 73 | 1.58 | 46.1 | 182 | True |
| 2025-01-15 13:30 | 2025-01-15 08:30 | 180.20 | 3.93 | 45.8 | 163 | True |
| 2022-08-05 13:30 | 2022-08-05 08:30 | -131.80 | 2.96 | 44.5 | 260 | True |
| 2024-05-14 13:30 | 2024-05-14 08:30 | -76.6 | 1.73 | 44.3 | 173 | True |
| 2022-08-25 07:16 | 2022-08-25 02:16 | 85.4 | 2.11 | 40.5 | 89 | False |
| 2021-07-13 12:30 | 2021-07-13 08:30 | -61.4 | 1.54 | 40 | 7,544 | True |
| 2023-07-12 13:30 | 2023-07-12 08:30 | 69.7 | 1.77 | 39.4 | 173 | True |
| 2019-12-06 06:01 | 2019-12-06 01:01 | 15.2 | 0.39 | 39.4 | 1,651 | False |
| 2025-08-14 13:30 | 2025-08-14 08:30 | -91.2 | 2.32 | 39.3 | 338 | True |
| 2022-09-21 19:00 | 2022-09-21 14:00 | -155.00 | 3.97 | 39 | 222 | True |
| 2022-06-10 13:30 | 2022-06-10 08:30 | -180.90 | 4.64 | 39 | 188 | True |
| 2024-02-13 13:30 | 2024-02-13 08:30 | -112.30 | 2.96 | 38 | 187 | True |
| 2022-10-07 13:30 | 2022-10-07 08:30 | -134.70 | 3.62 | 37.2 | 220 | True |
| 2023-02-14 13:30 | 2023-02-14 08:30 | -104.30 | 2.93 | 35.6 | 208 | True |
Largest outside news windows:
| server | et | move_pts | sigma_pts | z | tick_volume |
|---|---|---|---|---|---|
| 2025-05-12 08:00 | 2025-05-12 03:00 | 183.60 | 3.53 | 52 | 382 |
| 2022-08-25 07:16 | 2022-08-25 02:16 | 85.4 | 2.11 | 40.5 | 89 |
| 2019-12-06 06:01 | 2019-12-06 01:01 | 15.2 | 0.39 | 39.4 | 1,651 |
| 2025-08-27 21:21 | 2025-08-27 16:21 | -200.40 | 5.72 | 35 | 349 |
| 2019-11-18 07:17 | 2019-11-18 02:17 | 24.8 | 0.74 | 33.4 | 4,020 |
| 2026-01-28 06:00 | 2026-01-28 01:00 | 52.3 | 1.68 | 31.2 | 410 |
| 2019-09-02 15:49 | 2019-09-02 11:49 | -56 | 1.9 | 29.5 | 5,624 |
| 2025-08-12 06:02 | 2025-08-12 01:02 | -48.6 | 1.69 | 28.8 | 248 |
| 2026-03-26 20:11 | 2026-03-26 16:11 | 197.80 | 6.92 | 28.6 | 332 |
| 2023-01-18 02:40 | 2023-01-17 21:40 | 45.1 | 1.69 | 26.7 | 200 |
| 2019-11-26 01:46 | 2019-11-25 20:46 | 28 | 1.06 | 26.4 | 2,821 |
| 2019-08-23 12:00 | 2019-08-23 08:00 | -46.8 | 1.78 | 26.3 | 4,719 |
| 2025-04-16 09:27 | 2025-04-16 04:27 | 182.10 | 7.14 | 25.5 | 205 |
| 2025-05-09 12:26 | 2025-05-09 07:26 | -78.6 | 3.15 | 24.9 | 215 |
| 2025-01-29 06:00 | 2025-01-29 01:00 | 62.8 | 2.53 | 24.9 | 134 |

**Roll / jump check around quarterly futures expiries (third Friday of Mar/Jun/Sep/Dec ±10 days) vs control windows (third Friday of other months).** Statistic per window: the largest 1-minute |return| in quiet hours (z vs past sigma), the largest daily-break gap and weekend gap (z vs trailing sd).
|  | quarterly (expiry) windows | control windows |
|---|---|---|
| windows | 29 | 57 |
| median_quiet_max_z | 12.1 | 13.3 |
| share_quiet_z>8 | 100.00 | 98.2 |
| median_break_gap_max_z | 1.6 | 2.1 |
| share_break_gap_z>4 | 10.3 | 26.3 |
| median_weekend_gap_max_z | 0.8 | 0.8 |
| share_weekend_gap_z>4 | 0 | 3.5 |
| max_abs_quiet_move_pct | 0.864 | 1.011 |
| max_abs_break_gap_pct | 0.781 | 3.59 |
Typical gap sizes: daily-break gap sd 0.258%, weekend gap sd 0.614%. Of the quarterly windows' largest quiet moves, 24.1% were positive (an unadjusted contango roll would be consistently positive after 2022).

**Verdict (INFERRED, moderate confidence):** **no futures-roll signature**: quarterly windows are not more jumpy than control windows (median largest quiet z 12.1 vs 13.3; break gaps z>4 in 10.3% vs 26.3%; largest quiet move 0.864% vs 1.011%), and the largest moves do not cluster at a common time or expiry offset. The series looks **cash-like (or continuously/back-adjusted)**. These tests cannot separate 'cash index CFD' from 'adjusted futures'; a 0.2–1% basis jump on every roll would have been visible, a smoothly amortised basis would not.

Quarterly windows in detail:
| expiry | quiet_max_z | quiet_day_offset | quiet_et | quiet_move_pct | break_gap_max_z | break_gap_pct | break_gap_day_offset | weekend_gap_max_z | weekend_gap_pct |
|---|---|---|---|---|---|---|---|---|---|
| 2019-09-20 | 21.8 | 0 | 13:13 | -0.498 | 1 | 0.088 | -8 | — | — |
| 2019-12-20 | 17.6 | -7 | 07:58 | -0.265 | 2.2 | 0.114 | -8 | 0.6 | 0.189 |
| 2020-03-20 | 12.1 | -8 | 09:54 | 0.864 | 5.5 | 0.781 | 3 | 3 | -3.261 |
| 2020-06-19 | 12.1 | 3 | 21:15 | -0.365 | 2.2 | 0.441 | 10 | 1.3 | -1.028 |
| 2020-09-18 | 9 | -8 | 03:34 | -0.436 | 1.9 | -0.601 | -10 | 0.9 | 0.749 |
| 2020-12-18 | 15.3 | -4 | 08:14 | -0.204 | 0.7 | 0.22 | -4 | 0.6 | 0.436 |
| 2021-03-19 | 15.9 | 0 | 09:00 | -0.543 | 1.2 | 0.295 | -8 | 0.4 | -0.225 |
| 2021-06-18 | 14.8 | 6 | 04:01 | 0.144 | 1.9 | 0.355 | -4 | 0.6 | -0.249 |
| 2021-09-17 | 14.6 | 4 | 08:14 | -0.245 | 1.8 | -0.285 | 4 | 1 | -0.237 |
| 2021-12-17 | 9.7 | -4 | 00:28 | -0.056 | 2.3 | 0.453 | 3 | 0.7 | 0.138 |
| 2022-03-18 | 22.5 | -7 | 06:23 | 0.789 | 0.5 | 0.345 | 10 | 0.8 | 0.449 |
| 2022-06-17 | 10.8 | -10 | 06:59 | -0.302 | 1.1 | 0.312 | -2 | 2 | -1.342 |
| 2022-09-16 | 13 | 5 | 01:57 | -0.194 | 1.6 | -0.132 | -1 | 0.7 | 0.464 |
| 2022-12-16 | 10.8 | -7 | 01:55 | 0.101 | 2.6 | 0.517 | 4 | 0.3 | -0.23 |
| 2023-03-17 | 10.5 | 3 | 00:39 | -0.2 | 1.2 | 0.368 | -2 | 3.1 | 1.169 |
| 2023-06-16 | 9 | -4 | 23:34 | 0.089 | 1 | 0.272 | -4 | 1.2 | 0.396 |
| 2023-09-15 | 11.3 | 10 | 20:49 | -0.122 | 0.4 | -0.112 | -10 | 0.6 | 0.162 |
| 2023-12-15 | 13.2 | 7 | 08:36 | 0.21 | 1.7 | 0.124 | -2 | 0.7 | 0.173 |
| 2024-03-15 | 9.9 | -8 | 16:15 | -0.353 | 3.2 | 0.2 | -8 | 0.8 | 0.136 |
| 2024-06-21 | 10.5 | 5 | 16:01 | -0.285 | 0.6 | -0.039 | -9 | 0.8 | 0.114 |
| 2024-09-20 | 10.9 | -8 | 14:51 | -0.359 | 0.6 | 0.077 | -2 | 0.3 | 0.054 |
| 2024-12-20 | 13.7 | -10 | 00:30 | -0.057 | 8.9 | 0.466 | -8 | 0.2 | 0.037 |
| 2025-03-21 | 8.8 | 4 | 09:43 | -0.199 | 2.9 | -0.379 | 10 | 1 | 0.544 |
| 2025-06-20 | 15.8 | -8 | 19:59 | -0.267 | 0.7 | 0.392 | -1 | 1.6 | -1.185 |
| 2025-09-19 | 10.6 | -4 | 04:01 | -0.098 | 1.2 | 0.09 | -2 | 0.1 | -0.047 |
| 2025-12-19 | 14.6 | -10 | 05:39 | -0.183 | 4.9 | -0.472 | -8 | 0.4 | 0.232 |
| 2026-03-20 | 28.6 | 6 | 16:11 | 0.831 | 1.6 | 0.195 | 10 | 1.6 | -0.974 |
| 2026-06-19 | 13.1 | -8 | 08:22 | -0.349 | 1.6 | -0.252 | -9 | 2.2 | 1.206 |
| 2026-09-18 | 11.4 | 0 | 07:05 | -0.158 | 0.8 | 0.103 | 3 | 2.1 | -1.205 |

**Are bars aggregates of ticks? (MEASURED)** Minute-by-minute comparison of the M1 bar with bid/ask OHLC rebuilt from ticks:
| year | minutes_compared | O bar==bid % | H bar==bid % | L bar==bid % | C bar==bid % | O bar==ask % | H bar==ask % | L bar==ask % | C bar==ask % | tick_vol==ticks % | tick_vol==bid-changes % | sum(tick_vol)/sum(ticks) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2,021 | 123,339 | 100.00 | 99.99 | 99.99 | 99.97 | 0 | 0 | 0 | 0 | 97.67 | 99.1 | 1.093 |
| 2,022 | 340,322 | 100.00 | 100.00 | 100.00 | 99.97 | 0.03 | 0.02 | 0.01 | 0.03 | 86.98 | 83.01 | 0.99 |
| 2,023 | 336,658 | 99.99 | 100.00 | 99.98 | 99.97 | 0 | 0 | 0 | 0 | 97.23 | 95.68 | 0.996 |
| 2,024 | 354,230 | 100.00 | 100.00 | 100.00 | 99.97 | 0 | 0 | 0 | 0 | 91.62 | 98.19 | 0.996 |
| 2,025 | 350,675 | 99.99 | 99.99 | 99.99 | 99.95 | 0 | 0 | 0 | 0 | 99.51 | 99.81 | 1 |
| 2,026 | 266,965 | 99.99 | 99.99 | 99.99 | 99.93 | 0 | 0 | 0 | 0 | 99.92 | 99.91 | 1 |
| ALL | 1,772,189 | 100.00 | 99.99 | 99.99 | 99.96 | 0.01 | 0 | 0 | 0.01 | 95.03 | 95.44 | 0.999 |
Bars without any tick in the overlap: 1,390 (a tick-history gap of those minutes); tick minutes without a bar: 0. → OHLC are **bid-based** (≥99.9% exact vs bid, ~0% vs ask). `tick_volume` counts ticks but equals the tick count only in 87–100% of minutes depending on the year (2021 bars count ~9% more ticks than the tick history contains).

**tick_volume / real_volume by year (MEASURED):** `real_volume` is zero everywhere; `tick_volume` is **not comparable across years** (feed density changed ~13×):
| year | bars | tick_volume_mean | tick_volume_median | tick_volume_p99 | tick_volume_max | tick_volume_zero_bars | real_volume_nonzero_bars |
|---|---|---|---|---|---|---|---|
| 2019 | 156,827 | 297.20 | 208.00 | 1,504.0 | 7,063 | 0 | 0 |
| 2020 | 334,642 | 783.00 | 537.00 | 3,884.0 | 20,043 | 0 | 0 |
| 2021 | 329,875 | 418.40 | 216.00 | 2,759.0 | 20,835 | 0 | 0 |
| 2022 | 340,334 | 128.90 | 85 | 644.00 | 940 | 0 | 0 |
| 2023 | 336,658 | 62.6 | 43 | 215.00 | 301 | 0 | 0 |
| 2024 | 354,286 | 83 | 64 | 209.00 | 450 | 0 | 0 |
| 2025 | 350,730 | 134.60 | 108.00 | 384.00 | 513 | 0 | 0 |
| 2026 | 267,860 | 342.70 | 353.00 | 576.00 | 591 | 0 | 0 |

## 9. Task 6 — Volatility calibration and cost hurdles
Definitions: P(T) = open of the M1 bar at ET time T. 5 min/1 h: non-overlapping blocks inside the cash session (RTH) from 09:30; 6 h: 09:30→15:30 ET; overnight: 16:00 ET → next 09:30 ET, Mon–Thu nights; 5 days: Fri 16:00 → next Fri 16:00. σ = std of the price change in **index points** (MEASURED); `mean abs move / σ` is 0.80 for a normal distribution.

Average price level by year (M1 close mean):
| 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 | last 12 months |
|---|---|---|---|---|---|---|---|---|
| 7,997 | 10,271 | 14,480 | 12,748 | 14,212 | 19,108 | 22,534 | 27,601 | 27,042 |

**5min|RTH**
| year | N | sigma (idx pts) | mean abs move / sigma |
|---|---|---|---|
| 2019 | 8,820 | 6.66 | 0.65 |
| 2020 | 19,706 | 16.99 | 0.66 |
| 2021 | 19,477 | 14.86 | 0.68 |
| 2022 | 19,659 | 22.21 | 0.71 |
| 2023 | 19,539 | 14.28 | 0.72 |
| 2024 | 19,842 | 18.45 | 0.69 |
| 2025 | 19,651 | 26.24 | 0.63 |
| 2026 | 14,969 | 29.72 | 0.69 |
| ALL | 141,663 | 20.16 | 0.65 |
| last 12 months | 19,690 | 28.7 | 0.68 |

**1h|RTH**
| year | N | sigma (idx pts) | mean abs move / sigma |
|---|---|---|---|
| 2019 | 700 | 22.95 | 0.65 |
| 2020 | 1,518 | 52.1 | 0.7 |
| 2021 | 1,510 | 50.5 | 0.7 |
| 2022 | 1,518 | 77.56 | 0.74 |
| 2023 | 1,512 | 49.47 | 0.75 |
| 2024 | 1,524 | 63.61 | 0.71 |
| 2025 | 1,512 | 91.3 | 0.66 |
| 2026 | 1,150 | 102.56 | 0.69 |
| ALL | 10,944 | 68.95 | 0.67 |
| last 12 months | 1,513 | 101.02 | 0.69 |

**5min|all hours**
| year | N | sigma (idx pts) | mean abs move / sigma |
|---|---|---|---|
| 2019 | 31,346 | 4.69 | 0.59 |
| 2020 | 66,841 | 11.77 | 0.61 |
| 2021 | 65,763 | 9.82 | 0.61 |
| 2022 | 67,843 | 14.96 | 0.63 |
| 2023 | 67,132 | 9.23 | 0.62 |
| 2024 | 70,661 | 12.2 | 0.6 |
| 2025 | 70,020 | 17.25 | 0.57 |
| 2026 | 53,470 | 20.57 | 0.65 |
| ALL | 493,076 | 13.6 | 0.58 |
| last 12 months | 70,170 | 19.72 | 0.64 |

**1h|all hours**
| year | N | sigma (idx pts) | mean abs move / sigma |
|---|---|---|---|
| 2019 | 2,606 | 16.98 | 0.61 |
| 2020 | 5,445 | 39.54 | 0.63 |
| 2021 | 5,144 | 32.82 | 0.65 |
| 2022 | 5,408 | 51.75 | 0.65 |
| 2023 | 5,276 | 31.91 | 0.65 |
| 2024 | 5,648 | 42.27 | 0.62 |
| 2025 | 5,530 | 60.71 | 0.59 |
| 2026 | 4,103 | 73.54 | 0.66 |
| ALL | 39,160 | 47.22 | 0.6 |
| last 12 months | 5,382 | 70.42 | 0.65 |

**6h|09:30-15:30 ET**
| year | N | sigma (idx pts) | mean abs move / sigma |
|---|---|---|---|
| 2019 | 114 | 55.76 | 0.75 |
| 2020 | 244 | 124.30 | 0.76 |
| 2021 | 240 | 130.44 | 0.78 |
| 2022 | 246 | 205.17 | 0.81 |
| 2023 | 247 | 131.50 | 0.8 |
| 2024 | 249 | 165.19 | 0.74 |
| 2025 | 247 | 250.18 | 0.69 |
| 2026 | 189 | 253.43 | 0.78 |
| ALL | 1,776 | 179.36 | 0.72 |
| last 12 months | 248 | 253.37 | 0.77 |

**6.5h|09:30-16:00 ET (full cash session)**
| year | N | sigma (idx pts) | mean abs move / sigma |
|---|---|---|---|
| 2019 | 114 | 58.17 | 0.76 |
| 2020 | 245 | 136.12 | 0.76 |
| 2021 | 31 | 123.73 | 0.78 |
| 2022 | 147 | 210.57 | 0.82 |
| 2023 | 77 | 128.62 | 0.81 |
| 2024 | 249 | 170.81 | 0.74 |
| 2025 | 240 | 247.31 | 0.66 |
| 2026 | 189 | 253.83 | 0.78 |
| ALL | 1,292 | 191.01 | 0.71 |
| last 12 months | 248 | 256.84 | 0.76 |

**overnight|Mon-Thu nights**
| year | N | sigma (idx pts) | mean abs move / sigma |
|---|---|---|---|
| 2019 | 91 | 40.88 | 0.79 |
| 2020 | 197 | 105.10 | 0.72 |
| 2021 | 25 | 78.41 | 0.8 |
| 2022 | 116 | 131.94 | 0.79 |
| 2023 | 62 | 81.19 | 0.79 |
| 2024 | 197 | 127.13 | 0.75 |
| 2025 | 190 | 152.56 | 0.72 |
| 2026 | 151 | 244.89 | 0.75 |
| ALL | 1,029 | 144.89 | 0.69 |
| last 12 months | 198 | 228.52 | 0.74 |

**weekend|Fri 16:00 - Mon 09:30**
| year | N | sigma (idx pts) | mean abs move / sigma |
|---|---|---|---|
| 2019 | 23 | 54.21 | 0.73 |
| 2020 | 45 | 114.91 | 0.77 |
| 2021 | 6 | 101.35 | 0.87 |
| 2022 | 30 | 125.09 | 0.74 |
| 2023 | 13 | 68.1 | 0.77 |
| 2024 | 50 | 170.98 | 0.54 |
| 2025 | 48 | 246.32 | 0.75 |
| 2026 | 37 | 257.62 | 0.75 |
| ALL | 252 | 179.12 | 0.66 |
| last 12 months | 48 | 247.14 | 0.81 |

**5d|Fri 16:00 - next Fri 16:00**
| year | N | sigma (idx pts) | mean abs move / sigma |
|---|---|---|---|
| 2019 | 22 | 129.80 | 0.85 |
| 2020 | 42 | 389.55 | 0.75 |
| 2021 | 5 | 500.91 | 0.87 |
| 2022 | 28 | 502.66 | 0.91 |
| 2023 | 14 | 424.46 | 0.79 |
| 2024 | 48 | 488.36 | 0.79 |
| 2025 | 44 | 515.70 | 0.83 |
| 2026 | 33 | 696.25 | 0.76 |
| ALL | 236 | 486.75 | 0.78 |
| last 12 months | 43 | 661.46 | 0.78 |

Sigma used below = **last 12 months** (volatility in points scales with the price level, so older years are not comparable).

### Hurdle table (required hit rate for payoff 1:1: 0.5 + C / (1.6 σ))
C = one spread + slippage on both sides (**ASSUMED**: 0.5 pt/side base, 2 pt/side stress) + commission (0.0, weakly MEASURED) + swap × nights (INFERRED 'points' reading; long pays, short 0; 1 night overnight, 7 for a 5-day hold). Spreads: base = RTH median of the current regime; stress = the **widest quote seen anywhere in the current regime** (2.0 pts, MEASURED over 138,682 minutes), i.e. the worst-case spread at volatile times; a p99 of the per-minute median would equal the base in a quasi-fixed regime and would stress nothing. stress-alt = p99 of the per-minute spread in the worst past regime (09:30–10:00 ET for intraday, average of the 15:30–16:00 and 09:30–10:00 p99 for overnight), a scenario in which the broker re-prices to its worst past level. The last column re-computes the hit rate with the measured mean absolute move instead of 0.8σ.
| horizon | case | side | sigma_pts | spread | slippage (ASSUMED) | commission | swap | C_total_pts | required_hit_rate_% | required_hit_rate_% using measured mean abs move |
|---|---|---|---|---|---|---|---|---|---|---|
| 5min | base | n/a | 28.7 | 1.43 | 1 | 0 | 0 | 2.43 | 55.29 | 56.19 |
| 5min | stress (widest quote, current regime) | n/a | 28.7 | 2 | 4 | 0 | 0 | 6 | 63.07 | 65.27 |
| 5min | stress-alt (p99, worst past regime) | n/a | 28.7 | 3.4 | 4 | 0 | 0 | 7.4 | 66.11 | 68.84 |
| 1h | base | n/a | 101.00 | 1.43 | 1 | 0 | 0 | 2.43 | 51.5 | 51.75 |
| 1h | stress (widest quote, current regime) | n/a | 101.00 | 2 | 4 | 0 | 0 | 6 | 53.71 | 54.31 |
| 1h | stress-alt (p99, worst past regime) | n/a | 101.00 | 3.4 | 4 | 0 | 0 | 7.4 | 54.58 | 55.32 |
| 6h | base | n/a | 253.40 | 1.43 | 1 | 0 | 0 | 2.43 | 50.6 | 50.62 |
| 6h | stress (widest quote, current regime) | n/a | 253.40 | 2 | 4 | 0 | 0 | 6 | 51.48 | 51.53 |
| 6h | stress-alt (p99, worst past regime) | n/a | 253.40 | 3.4 | 4 | 0 | 0 | 7.4 | 51.83 | 51.89 |
| overnight | base | long | 228.50 | 1.43 | 1 | 0 | 4.29 | 6.72 | 51.84 | 52 |
| overnight | base | short | 228.50 | 1.43 | 1 | 0 | 0 | 2.43 | 50.66 | 50.72 |
| overnight | stress (widest quote, current regime) | long | 228.50 | 2 | 4 | 0 | 4.29 | 10.29 | 52.81 | 53.05 |
| overnight | stress (widest quote, current regime) | short | 228.50 | 2 | 4 | 0 | 0 | 6 | 51.64 | 51.78 |
| overnight | stress-alt (p99, worst past regime) | long | 228.50 | 3.4 | 4 | 0 | 4.29 | 11.69 | 53.2 | 53.47 |
| overnight | stress-alt (p99, worst past regime) | short | 228.50 | 3.4 | 4 | 0 | 0 | 7.4 | 52.02 | 52.2 |
| 5d | base | long | 661.50 | 1.43 | 1 | 0 | 30.03 | 32.46 | 53.07 | 53.15 |
| 5d | base | short | 661.50 | 1.43 | 1 | 0 | 0 | 2.43 | 50.23 | 50.24 |
| 5d | stress (widest quote, current regime) | long | 661.50 | 2 | 4 | 0 | 30.03 | 36.03 | 53.4 | 53.49 |
| 5d | stress (widest quote, current regime) | short | 661.50 | 2 | 4 | 0 | 0 | 6 | 50.57 | 50.58 |
| 5d | stress-alt (p99, worst past regime) | long | 661.50 | 3.4 | 4 | 0 | 30.03 | 37.43 | 53.54 | 53.63 |
| 5d | stress-alt (p99, worst past regime) | short | 661.50 | 3.4 | 4 | 0 | 0 | 7.4 | 50.7 | 50.72 |

### Against your earlier assumptions (spread 2/8 pts, swap 4.6 pt/night long, σ 19/65/160/150/700; same ASSUMED slippage)
| horizon | case | sigma assumed | sigma measured | C assumed | C measured | hit rate assumed % | hit rate: measured sigma, your C % | hit rate measured % | verdict |
|---|---|---|---|---|---|---|---|---|---|
| 5min | base | 19 | 28.7 | 3 | 2.43 | 59.87 | 56.53 | 55.29 | better |
| 5min | stress | 19 | 28.7 | 12 | 6 | 89.47 | 76.13 | 63.07 | better |
| 1h | base | 65 | 101.00 | 3 | 2.43 | 52.88 | 51.86 | 51.5 | better |
| 1h | stress | 65 | 101.00 | 12 | 6 | 61.54 | 57.42 | 53.71 | better |
| 6h | base | 160 | 253.40 | 3 | 2.43 | 51.17 | 50.74 | 50.6 | better |
| 6h | stress | 160 | 253.40 | 12 | 6 | 54.69 | 52.96 | 51.48 | better |
| overnight | base | 150 | 228.50 | 7.6 | 6.72 | 53.17 | 52.08 | 51.84 | better |
| overnight | stress | 150 | 228.50 | 16.6 | 10.29 | 56.92 | 54.54 | 52.81 | better |
| 5d | base | 700 | 661.50 | 35.2 | 32.46 | 53.14 | 53.33 | 53.07 | better |
| 5d | stress | 700 | 661.50 | 44.2 | 36.03 | 53.95 | 54.18 | 53.4 | better |

**Reading.** Measured sigma (last 12 months, index points) is higher than assumed at 5min, 1h, 6h, overnight and lower at 5d; sigma in points scales with the price level. The current-regime spread (1.43 pts) is below your 2-pt base. 10 of 10 cells need a lower hit rate than you assumed, 0 a higher one. The column 'hit rate: measured sigma, your C' keeps your costs and swaps in the measured sigma, so it splits each change into a volatility part and a cost part. At 5 min the hurdle falls by 4.6 pp in the base case (3.3 from sigma, 1.2 from cost) and by 26.4 pp at stress (13.3 from sigma, 13.1 from the 2.0-pt vs 8-pt stress spread). Caveat: the measured stress spread (2.0 pts) is the widest quote of a single regime that started 2026-05-14 (123 days, including 21 detected 08:30 ET release days and 6 14:00 ET Fed days). It holds only while the broker keeps this regime: it has run spreads up to 3.0 pts for months (stress-alt rows) and quoted single ticks up to 69.3 pts in earlier regimes. Re-measure it after any re-pricing. While the quoted spread stays fixed, event-time costs show up as slippage, which is still ASSUMED.

## 10. Limitations and what could not be verified
- Slippage cannot be measured without live executions; 0.5 / 2.0 points per side are ASSUMED, and market-execution fills at this broker may differ from quote-based costs.
- Whether swap and commission are charged is not established (swap_mode DISABLED with populated values; one USTEC round trip in the deal history). Money-based checks are impossible at 0.01-0.02 lots because swap rounds to 0.00.
- No spread history before 2021-08-16 (bar spread = 0). The 2019-2021 M1 data are usable for price/volatility, not for costs.
- The spread is quasi-fixed and re-priced by the broker; percentiles from different regimes must not be pooled. Current-regime statistics rest on ~123 days.
- The weekly server-clock detection depends on a cash-open step in 1-min range; weeks with margin < 1.15 or < 3 trading days were treated as uninformative. The exact date of the UTC→London switch is unidentifiable inside the winter ambiguity.
- Session schedules are inferred per quarter from the bars (≥50% presence); quarters that contain a schedule change get a blended schedule, so gap counts near the break edges in those quarters are approximate.
- Events are detected empirically (APPROXIMATE) because no events file was supplied; 14:00 ET FOMC windows rest on few events per year, and range comparisons around detected events are circular by construction.
- The roll test has no external reference (no NDX cash index): it can exclude discrete unadjusted roll jumps but cannot distinguish a cash-like CFD from a smoothly adjusted futures series.
- tick_volume changed meaning/density across years (≈13× range) and the tick history in 2021 contains ~9% fewer ticks than the bars aggregated; do not use volume as a cross-year feature.
- Leverage and the live spread/swap values are snapshots at run time and change (leverage 400 and 3000 were both observed on 2026-10-05).

## 11. Questions you must answer
1. **Account type and execution model.** Is this a Pro/Standard/ECN account, and is execution market (the API says SYMBOL_TRADE_EXECUTION_MARKET, FOK|IOC) with a dealer-set spread? Is the 1.43-point USTEC spread contractually fixed or can it float/re-price?
2. **Commission.** Is there any commission on USTEC (per lot or per million)? The deal history shows 0.0 on one round trip only.
3. **Swap.** Does the account pay/receive swap on USTEC? swap_mode is DISABLED but swap_long = −428.93 points. Please check the symbol specification in the terminal (Market Watch → Specification) or ask IUX, and say whether this is a swap-free account.
4. **Rollover time.** At which server time are swaps applied (default would be server midnight = 19:00 ET)? The spread spike is at the post-break re-open shown in section 5.
5. **Events file.** Provide `events.csv` (event_name, datetime_et) to replace the APPROXIMATE event detection with real release times (set `AUDIT_EVENTS_CSV`).
6. **Slippage.** If you have live-fill logs, share them so the ASSUMED 0.5/2 pt per side can be replaced by a measurement.
7. **Cache location.** The tick cache is ~1 GB of parquet inside `audit/cache/`, which sits in a OneDrive-synced folder here; move it with `AUDIT_CACHE_DIR` if you do not want it synced.

## Files
`audit/out/cost_model_inputs.json` (machine-readable inputs with provenance), `audit/out/server_clock.json` (era-aware clock for `audit.tz.ServerClock.load`), `audit/out/*.csv` (full tables), `audit/out/run.log`. Re-run: see `audit/README.md`.
