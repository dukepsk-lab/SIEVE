# Independent review: US100 (USTEC.) data and cost audit, IUX MT5

Reviewed 2026-10-05 against `audit/report.md`, `audit/out/*` and the `audit/*.py` code. I made no edits to the implementer's
files. All my code is in `audit/review/rv_*.py`, and its outputs (small tables only) are in `audit/review/out/`. Raw live
pulls went to a scratch folder outside the repo. I did not call any order or position function, and read nothing from the
account except "is a session logged in".

**Input gaps in the review request.** The pasted request still contained two placeholders: the implementer's final summary
and the original audit prompt. I therefore treat `report.md` §1 (Summary) and §2 (Status table) as the implementer's claims.
If a separate final summary exists, paste it and I will check it claim by claim.

**Method.** I re-derived every headline number from raw data with my own code: the live MT5 terminal (read-only), the
implementer's raw tick and bar parquet files (re-pulled live for 3 tick days and 2 bar months, and found byte-identical),
and my own zoneinfo-based clock model. I imported the implementer's code only once, to test its saved clock helper as the
*subject* of a test (`rv_clock_vs_helper.py`).

---

## 1. Verdict: PASS WITH FIXES

> **Update 2026-10-05:** F1, F2, F3, F4 and F8 have been fixed, and you answered the cost questions (Pro account, no
> commission, no swap); see §8.
> The verdict below describes the audit as reviewed.

**Yes, the numbers can be used to update the cost-hurdle table and the data-sufficiency judgement, except the stress-case
spread and the by-year overnight, 5d and 6.5h sigmas.** Everything that drives the base case reproduces exactly from raw
data:

- the server clock (UTC-fixed until the 2021/22 winter, then London time; *not* NY-close);
- the spread units (1 index pt = 100 `point`);
- the current-regime spread of 1.43 pts and all the bucket percentiles I re-derived;
- last-12-month sigma for all five horizons;
- the swap arithmetic;
- the history extents (7.22 y of M1, 5.14 y of ticks) and the Sharpe floors (1.12 and 1.32);
- all 21 hurdle rows, to 0.00 pp.

I found no blocker. What must not go forward unchanged:

1. The **"stress" spread** is the p99 of the per-minute *median* spread. In a quasi-fixed spread regime that collapses to
   the base value (1.43 = 1.43), so the stress case stresses only slippage. This breaks the project rule "worst-case
   spread at volatile times".
2. The summary's **"better than your assumptions in every cell"** depends on that redefinition at stress. With measured
   sigma and the user's 8-pt stress spread, the 5-min stress hurdle is 76.1%, not 61.8%.
3. The **overnight, 6.5h, weekend and 5d samples silently drop nights with no 16:00 ET bar**. That selection removed
   exactly the 2025 tariff-crash nights (2025 overnight sigma 152.6 vs 173.9) and left N=25 of 208 nights in 2021. These
   rows sit in the JSON "inputs" file. The last-12-month values used for the hurdles are unaffected (228.52 vs 228.05).

Commission (0.0, n=1 round trip) and whether swap is charged at all (swap_mode = DISABLED) remain UNKNOWN. Every cost
number is therefore conditional on the user's answers in §7. The report says this honestly.

---

## 2. Findings (most severe first)

| id | sev | location | what is wrong | evidence | downstream impact | suggested fix |
|---|---|---|---|---|---|---|
| F1 | MAJOR | `t2_spread.py:310-313` (`cost_spreads.st` uses `s_med_pt`); `t6_vol.py:115-125`; report §9 | The stress spread is defined as the p99 of the per-minute **time-weighted median**. The worst spread inside a minute, which is what a market order can hit, is never used. In the current quasi-fixed regime this gives stress = base = 1.43. The "stress-alt" row (3.4) is also a median-based p99, and from the open bucket only; the same worst regime has an all-minute p99 of 5.0 (03:00 ET bucket p99 5.0; reviewer). | Reviewer, from raw ticks (`rv_spread.json`). Current regime, 09:30 ET bucket: p99 of the median = 1.43, worst tick = **2.00** (N=3,060). All history, 09:30 bucket: p99 of the per-minute max = **5.32**, p99.9 = **9.80** (N=39,657). Worst regime: p99 of the per-minute max = 9.93. The report's own level-neutral table shows s_max/day-median p99.9 of 8.9× at 09:30 and 15.7× at 08:30. | The stress column of the hurdle table understates cost. 5-min stress hurdle: **61.83%** as reported, 63.07% with the current regime's worst tick (2.0), **70.30%** with the all-history p99 of the minute max (5.32), 76.14% with the user's 8 pts (`rv_hurdle.csv`). 1h: 53.36 / 53.71 / 55.77 / 57.42. 6h and longer barely move. | Build stress spreads from `s_max` (the per-minute max) in the volatile windows (09:30 open, 08:30 and 14:00 events, the 18:00 re-open). Report three levels: current-regime worst tick, historical level-neutral p99 and p99.9 ratio × current level, and the user's 8 pts. Keep the label "stress" for the worst-case spread only. |
| F2 | MAJOR | report §1 (line 6) and §9 "Against your earlier assumptions" (lines 1156-1170); `t6_vol.py:138-155` | "10 of 10 cells need a lower hit rate than you assumed" is not a like-for-like comparison at stress. The user's 8-pt stress spread is compared with 1.43 pts, which (F1) is not a stress measure. The base-case "better" is genuine: spread 1.43 < 2.0 and sigma in points is higher. | Same formula with measured sigma and the 8-pt stress spread: 5min 76.14% vs the 89.47% assumed and the 61.83% reported. The "Reading" paragraph has the caveat, but the summary headline does not. | Overstated conclusion. A reader may drop the 8-pt stress assumption before any fill data exists. | Restate: base is better; stress is better only because the current regime has shown no spread spikes (max 2.0 over 4.7 months, 21 release days, 6 FOMC days). Recompute the stress row after F1. |
| F3 | MAJOR (scoped: JSON `volatility.sigma_by_year_*` and report §9 by-year/ALL rows; hurdle inputs unaffected) | `t6_vol.py:35-41` (`_diff` → `dropna`); `t6_vol.py:63-72` | P(16:00 ET) exists only if a bar is stamped 16:00 or 15:59. When the broker session ended earlier, the night is silently dropped. The selection is not random. In 2021-22 the session ended at 15:58 ET, and in 2025-03-31..04-08 the broker closed at 15:58 ET right after the EU DST change. Those 6 dropped 2025 nights are the tariff-crash nights (−853, −542, +594 pts). | Reviewer (`rv_vol.json`). Overnight N/sigma (implementer rule vs last-price-≤16:00 rule): 2021 **25/78.4 vs 193/91.4**; 2023 62/81.2 vs 197/93.0; 2025 190/152.6 vs 196/**173.9**; last 12 months 198/228.52 vs 199/228.05. The same mechanism explains 6.5h N=31 (2021) and 5d N=5 (2021). | Any use of by-year or ALL overnight, 6.5h, weekend or 5d sigma is biased low (2025: −12%) and under-sampled. `cost_model_inputs.json` exposes these as MEASURED with N but no selection warning. | Use an as-of price (last bar ≤ T within a tolerance), or report N_candidates / N_dropped per year and flag the dropped dates. Regenerate the tables. |
| F4 | MINOR | `t1_coverage.py:137-139` (early-close rule); report §4 "gaps that run to the daily break are US-holiday early closes" | 19 of the 89 "early close" gaps are not US-holiday half-days. 14 are broker session shifts in the 1–2 weeks after a DST change, where the session is defined in server time and updated late: the CFD closed at **14:59 ET** on 2021-11-08..11, 2022-03-28..30 and 2023-03-27, and at **15:58 ET** on 2025-03-31..04-08 (raw bars: break 20:58→23:00 server). The other 5 are four June-2021 Mondays closing at 13:59 ET and 2021-12-31 closing at 14:59 ET. All 19 are excluded from the ">60 min, excluding holidays" count. | `gaps_all.csv` rows 483-486, 506-508, 618, 872-879; reviewer's raw-bar check of 2025-03-24..04-17 (open step stays at 14:28-14:30, so the clock is right but the session ends early). | Data gaps are understated in the "other" count. More importantly, tradable hours in ET shift for up to ~1.5 weeks after DST changes, so a strategy that trades the cash close can find no quote. | Add a "session shift (DST lag)" class: start ≥ 14:59 ET on a non-holiday. List the affected dates as a tradability calendar. |
| F5 | MINOR | `t1_coverage.py:45-47` vs report §4 (`report.py:210`) | The report says "direct `copy_ticks_from` from 2019 gives 2021-08-16 13:54:26.625". The code calls `first_tick_after(sym, lo)`, where `lo` is the binary search's final lower bound (hi − 1 day), not 2019. The claimed independent cross-check was not performed. | `first_tick.json` shows identical values for both and `probes=12`. Reviewer: `copy_ticks_from(2015-01-01)` returns **2021-08-16 13:54:26.625**, and 56 biweekly 3-day probes from 2019-07-16 to 2021-08-10 all return 0 ticks. | The number is correct (now verified). The report claims a verification that did not happen. | Call `copy_ticks_from(first_bar_day)` as described, or correct the text. |
| F6 | MINOR | `report.py:569`, `report.py:578` (JSON `spread.before_2021_08`, `swap.charged`) | Values that are UNKNOWN carry `provenance: MEASURED` with `value: null`. | JSON listing. | A program reading the JSON can mistake UNKNOWN for a measurement. | Use a provenance of `UNKNOWN`. |
| F7 | MINOR | JSON `hurdle_table`, `comparison_with_user_assumptions` | Rows carry no per-field provenance or N. Each row mixes a MEASURED spread and sigma, ASSUMED slippage, an INFERRED swap and a "weakly measured" commission of 0 (n=1). | JSON listing. | Downstream code cannot tell which inputs are assumptions. | Add `provenance` per field and `n` for sigma and spread. |
| F8 | MINOR | `t6_vol.py:110-135`, `run.py:165-166` | Commission = 0.0 from **one** round trip is used in both base and stress, with no sensitivity row. The swap is handled conservatively (charged on longs although mode is DISABLED). Commission is not treated conservatively. | `deals`: USTEC. 2 deals, 0.02 lots. | If any commission exists, every hurdle is understated. At $1 per index point per lot, $1 per lot per round trip adds 1 pt (+41% of the 5-min base cost). | Add a commission-sensitivity row until question 3 is answered. |
| F9 | MINOR | report §2 status row "Rollover time: INFERRED" (line 24), §5 2b (line 562) | The 18:00 ET spread spike is the **market re-open after the futures halt**. It is not evidence of the swap-rollover time. The JSON note correctly says the rollover time is UNKNOWN; the status table presents it as INFERRED. | Code: the inferred minute is `argmax` of the re-open profile (`t2_spread.py:147-153`). | Swap timing could be modelled at the wrong minute. Matters only for holds that cross 18:00–19:00 ET. | Label it UNKNOWN (question 5). |
| F10 | MINOR | report §1 "re-set 28 times in the tick era" | 12 of the 29 "regimes" lie in the floating-spread period (2021-08-16..2022-01-10) and are artefacts of the 4% rule applied to a floating series. Broker re-pricings since 2022-01-11 number 16. | Regime table rows 1-12 have ≤5.2% of minutes at the modal value. | Overstates how often the broker re-prices. Minor for the regime-risk narrative. | Report the floating period and the fixed-markup re-sets separately. |
| F11 | MINOR | report §5 2b re-open window (`*_cur`, N=81 and 98); 2c event tables | p99 is shown on N=81 (≈ the max) without a caveat. The per-window N (`N_range_event`, `N_spread_event`, computed at `t2_spread.py:227`) is dropped by `window_summary` (`t2_spread.py:234-247`), so the event tables show percentiles without N. Events carry an "only 21/6 event days" caveat; the re-open window does not. | Report tables. | Small-sample tail numbers could be read as stable. | Show N per window and suppress p99 when N < 200. |
| F12 | MINOR | `tests/test_tz.py` | 30 tests pass, but none loads the **fitted** `out/server_clock.json`. The London rule is tested at 2 instants only, with no EU transition instants and no era-boundary test of the fitted clock. The era test uses a hypothetical `ny 5` era. | Test file. Reviewer test: the saved helper equals my zoneinfo model on **all 2,470,673 M1 bars** (0 differences) and on 6 spot checks (`rv_clock_vs_helper.json`). | None today (the helper is right). There is a regression risk if the clock is re-fitted. | Add tests on the saved clock: mismatch weeks in Mar and Oct/Nov, EU and US transition Sundays, era boundary. |
| F13 | MINOR | `t4_timemap.py:171`; JSON `server_clock.eras[1].start_utc` | The era start "2021-11-01 00:00 UTC" is a **server-date week label**, not a UTC instant. It is harmless only because UTC and London coincide in winter. | Code. | None unless someone moves the boundary into summer. | Rename the field or convert it. |
| F14 | MINOR | report §1 verdict sentence; §4 Sharpe table | "Data and costs support further research on horizons ≥ 1 h" is a cost statement. The data-sufficiency implication is not stated in the summary: at t = 3, only edges with annualised Sharpe ≥ **1.12** (M1, 7.22 y) or ≥ **1.32** (ticks or spread-modelled, 5.14 y) are detectable. The current cost regime is 4.7 months old, and clock, session and feed changes shorten the effective sample. | Report §4 (the stationarity caveat is there, but not in §1). | A reader may take "supports further research" to mean the data are sufficient for typical retail edges (Sharpe 0.5–1.0). They are not. | State the Sharpe floor and its consequence in §1. |

Checked and found correct, so not findings: spread units, LOCF, tick integrity, bar/tick aggregation, swap enum and
arithmetic, triple-swap day, live offset, mismatch-week handling, outlier past-only sigma, still-forming bar drop, roll
check logic, and the bar `spread` bias quantification.

---

## 3. Verification table (my own code; tolerance: exact for counts, ±0.01 pt for spreads, ±0.01 pt for sigma, ±0.01 pp for hit rates, ±10 min for the open-step minute)

| claim (implementer) | my independent check | implementer | mine | result |
|---|---|---|---|---|
| Spread, 09:30-09:59 ET, current regime (since 2026-05-14) | per-minute time-weighted median, LOCF ≤5 min, raw ticks, own clock (`rv_spread.py`) | N 3,060 · p50 1.43 · p99 1.43 · max 2.0 | N 3,060 · 1.43 · 1.43 · 2.0 | match |
| Spread, 03:00-03:29 ET (quiet), current regime | same | N 3,060 · 1.43 · 1.43 · max 1.43 | N 3,060 · 1.43 · 1.43 · 1.43 | match |
| Spread, 09:30 bucket, all tick history | same | N 39,657 · p50 1.21 · p90 2.6 · p99 3.0 · max 17.7 | 39,657 · 1.21 · 2.6 · 3.0 · 17.7 | match |
| Spread, 03:00 bucket, all tick history | same | N 39,630 · 1.14 · 2.6 · 3.0 · 12.2 | 39,630 · 1.14 · 2.6 · 3.0 · 12.2 | match |
| Worst regime (2024-07-23..10-27), open bucket | same | N 2,070 · p50 3.0 · p99 3.4 · max 10.2 | 2,070 · 3.0 · 3.4 · 10.2 | match |
| Spread units (1 idx pt = 100 `point`) | live `symbol_info` (digits 2, point 0.01); live ask−bid 1.43 = `spread` field 143 × 0.01; cached ticks vs live re-pull | 1.43 pts | 1.43 pts; 300 pts = 3.00 (2024-08-14); 215 = 2.15 (2022-03-09) | match |
| Raw tick cache integrity | live `copy_ticks_range` for 2022-03-09, 2024-08-14, 2026-09-16 vs cache parquet | — | identical length, time_msc, bid, ask (314,826 / 124,612 / 537,542 ticks) | match |
| M1 bar count, 2024-09 and 2025-11 | live `copy_rates_from_pos` vs implementer's monthly raw file | 28,661 / 26,357 (cache) | 28,661 / 26,357, OHLC identical | match |
| Gaps ≥ 5 missing min, 2024-09 | bar-to-bar gaps, own break/weekend rule (`rv_gaps.py`) | 6 | 5 | match (Labor Day close is one gap in my method; their schedule splits it into 238 + 5 min) |
| Gaps ≥ 5 missing min, 2025-11 | same | 7 | 7, identical start times | match |
| Earliest M1 bar | `copy_rates_from_pos(…, 0, 4,000,000)` (a different call); range 2010→2019-07-16 | 2019-07-16 07:59 | 2019-07-16 07:59 (2,470,673 bars at 05:36 = 2,470,652 + 21 later minutes) | match |
| Latest M1 bar at run, forming bar dropped | code `mt5io.py:205`; count arithmetic above | 2026-10-05 05:15 (server now 05:16:51) | consistent | match (the run instant itself cannot be re-observed) |
| Earliest tick | `copy_ticks_from(2015-01-01)` plus 56 biweekly probes 2019-07..2021-08 | 2021-08-16 13:54:26.625 | 2021-08-16 13:54:26.625; no ticks before | match (but see F5) |
| Swap pts/night, long / short | raw `symbol_info`: swap_long −428.93 × point 0.01; tick_value/tick_size = 1 USD/pt/lot; contract 1 | −4.2893 / 0.0; 5.08% p.a. at 30,820.4 | −4.2893 / 0.0; 5.083% at live mid 30,800.6 | match |
| Triple-swap day | `swap_rollover3days` = 5 (ENUM_DAY_OF_WEEK: 5 = Friday) | Friday | Friday | match |
| sigma 1h RTH, 2024 | own ET clock, P(T) = open at T else close at T−1 (`rv_vol.py`) | 63.61 (N 1,524) | 63.61 (N 1,524) | match |
| sigma 6h, 5min, overnight, 5d (hurdle inputs) | same | 250.18 (2025, N 247); 28.69 (12m, N 19,689); 228.52 (12m, N 198); 661.46 (12m, N 43) | identical values and N | match |
| Cash-open server minute: winter week 2025-01-13 | unconstrained argmax 06:00–22:00 server of the 10-min fwd/back range ratio (`rv_time.py`) | 14:30 (margin 1.10, marked uninformative) | 14:30 (tied with 13:29, the CPI-day release) | match (winter does not separate London from ET+5) |
| Cash-open server minute: summer week 2025-07-14 | same | 14:30 | 14:27 (peak of the forward window) | match |
| Cash-open server minute: mismatch weeks 2025-03-17 / 2024-10-28 / 2026-03-16 | same | 13:30 / 13:30 / 13:30 | 13:27 / 13:29 / 13:24 (top 3 contain 13:29 and 13:30) | match |
| Clock era 1 (UTC-fixed), summer 2021-07-12 | same | 13:30 | 13:30 | match |
| London vs US-DST-linked clock | **FOMC 14:00 ET** in the mismatch weeks (dates from the public Fed calendar, reviewer-supplied, APPROXIMATE): largest range at 18:00 server on 2022-03-16, 2023-03-22, 2024-03-20 and 2025-03-19 (10.9–15× baseline; 19:00 only 2.3–8.8×). Oct/Nov: press-conference spike at 18:35–18:38 (London) | London | London; ET+5 rejected | match |
| London vs US-DST-linked clock (third test) | daily re-open in **server** time, London era Mon-Thu: normal weeks 23:00 / 23:05 / 23:30 (815 days), mismatch weeks 22:00 / 22:05 / 22:30 (59 days). The underlying halts 17:00–18:00 ET, so the server clock moves 1 h against ET in mismatch weeks | London | London | match |
| Live offset | tick `time_msc` − PC UTC; PC vs HTTP Date (google 1.19 s, apple 0.64 s, example.com 0.69 s) | UTC+1 (3,599.7 s) | UTC+1 (3,599.72 s, residual −0.28 s) | match |
| Saved clock helper | `ServerClock.load(server_clock.json).to_et` vs my zoneinfo model on every M1 bar | — | 0 of 2,470,673 differ | match |
| Bars are bid-based | live ticks rebuilt to M1 for 3 days | ≥99.9% vs bid | O/H/L 100%, C ≥99.92% vs bid, 0% vs ask | match |
| Hurdle table (21 rows) | recomputed 0.5 + C/(1.6σ) from the JSON inputs (`rv_hurdle.py`) | — | max abs diff 0.00 pp | match |
| Unit tests | `python -m pytest audit/tests -q` | 30 pass | 30 pass | match (coverage gap F12) |
| Pipeline reproduces from a clean cache | copy of the code run in scratch with a fresh `AUDIT_CACHE_DIR` | — | `mt5.initialize` IPC timeout: the IUX terminal started a **LiveUpdate** at 11:47 (an updater process was running) and was not available; I did not interfere with it | **cannot verify** |

---

## 4. Safe to use (with conditions)

- **Server clock**: `audit/out/server_clock.json`, through `audit.tz.ServerClock`. 09:30 ET = 14:30 server in normal weeks
  and 13:30 in the US/EU mismatch weeks; UTC-fixed before the 2021/22 winter. Confirmed by four independent methods.
  Condition: re-check after every DST change; the broker's *session* shifts late (F4) even though the clock is right.
- **Units**: 1 index pt = 100 `point` = 1 USD per 1.0 lot.
- **Spread, current regime**: 1.43 pts (base, RTH p50 and p99), worst tick 2.0. Condition: valid only while the broker
  keeps this level (since 2026-05-14, 123 days). Re-measure monthly.
- **Spread percentiles by 30-min bucket and regime table**: reproduce exactly. Condition: never pool across regimes.
- **sigma, last 12 months**: 28.69 / 101.02 / 253.37 / 228.52 / 661.46 pts (5min / 1h / 6h / overnight / 5d), N as
  reported. Condition: these are point values at an average level of about 27,036 while price is now about 30,800. If
  sigma scales with price, current sigma in points is about 14% higher, which slightly lowers the hurdles.
- **Base-case hurdle rows**: 55.29 / 51.50 / 50.60%, overnight 51.84% long and 50.66% short, 5d 53.07% long and 50.23%
  short. Condition: commission = 0 and the swap reading are unconfirmed (questions 3 and 4).
- **Swap arithmetic** (*if* swap is charged and read as POINTS): long −4.2893 pts/night, short 0, Friday ×3, 7 nights per
  week.
- **History extents and data sufficiency**: M1 7.22 y (from 2019-07-16), ticks 5.14 y (from 2021-08-16), Sharpe floors at
  t = 3 of 1.12 and 1.32. Condition: these are upper bounds on information; effective samples are shorter (F14).
- **Integrity facts**: no duplicate or non-monotonic bars, 1 crossed tick, bars bid-based, `tick_volume` not comparable
  across years, no futures-roll jump signature (INFERRED, moderate confidence).

## 5. Do not use until fixed

- ~~Spread "stress (p99, current regime)" = 1.43 as the worst-case spread (F1).~~ **Fixed (§8):** stress is now 2.0, the
  current regime's widest quote. "stress-alt" = 3.4 remains a re-pricing scenario (the broker returning to its worst past
  level), not a spike measure.
- ~~Stress hurdle rows and the "better than your assumptions" stress verdicts (F1, F2).~~ **Fixed (§8).**
- ~~By-year and ALL sigma for overnight, 6.5h, weekend and 5d (F3).~~ **Fixed (§8).**
- ~~"Early close" gap labels as a holiday calendar (F4).~~ **Fixed (§8):** DST session shifts are now a separate class.
- **Rollover time 18:00 ET** as a swap time (F9). No longer affects costs, because no swap is charged.
- ~~Commission = 0 as a fact (F8).~~ **Resolved (§8):** you confirmed no commission.

## 6. What to fix or re-run, in priority order

| # | fix | effort |
|---|---|---|
| 1 | F1 + F2: stress spread from `s_max` in volatile windows (current-regime worst tick; level-neutral historical p99/p99.9 × current level; user 8 pts). Regenerate the hurdle, the comparison and the §1 text | 1–2 h |
| 2 | F3: as-of pricing or explicit drop accounting for overnight, 6.5h, weekend and 5d; regenerate the by-year tables and the JSON | 1 h |
| 3 | F8: commission-sensitivity row; F6/F7: UNKNOWN provenance plus per-field provenance and N in the JSON | 45 min |
| 4 | F4: "session shift (DST lag)" gap class plus a tradability calendar | 1 h |
| 5 | F5, F9, F10, F11, F13, F14: text and label corrections; N per event window | 1 h |
| 6 | F12: tests on the saved clock (transition Sundays, mismatch weeks, era boundary) | 30 min |
| 7 | Clean-cache rerun of the pipeline once the terminal update finishes (`AUDIT_CACHE_DIR` set to a fresh folder outside OneDrive) and a diff of `cost_model_inputs.json` | ~15 min machine time |

## 7. Open questions only you can answer

1. **Implementer's final summary and original prompt**: both were placeholders in the review request. Provide them if you
   want a claim-by-claim check beyond report §1 and §2.
2. ~~Account and symbol~~ **Answered: Pro**, which matches the measured symbol `IUX Markets Pro\Index\USTEC.`.
3. ~~Commission~~ **Answered: none.**
4. ~~Swap~~ **Answered: not charged.**
5. ~~Swap rollover time~~ **Not needed**, because no swap is charged.
6. ~~Stress definition~~ **Answered: 2.0 pts** (the current regime's widest quote).
7. **Slippage**: you answered "OK". I read that as "no fill logs yet", so slippage stays ASSUMED at 0.5/2 pts per side.
8. ~~MT5 terminal~~ The update has finished; the pipeline has been re-run since.

---

## 8. Fix log

**2026-10-05: F1 and F2 fixed.** You chose a stress spread of 2.0 pts (question 6). It is computed from the data, not
hard-coded: the widest quote seen anywhere in the current regime, which is 2.0 pts over 138,682 minutes. It will update if
the pipeline is re-run after a re-price.

| file | change |
|---|---|
| `t2_spread.py` (`cost_spreads`) | adds `regime_current` (all minutes of the current regime); its `max_tick` is the stress spread |
| `t6_vol.py` (`hurdle`) | stress = the widest quote for every horizon; the case is renamed `stress (widest quote, current regime)`; stress-alt unchanged, now described as a re-pricing scenario |
| `t6_vol.py` (`compare_with_assumptions`) | new column `hit rate: measured sigma, your C %`, which splits each change into a volatility part and a cost part |
| `report.py` | §1 summary, §9 hurdle definition and the "Reading" paragraph rewritten; the split sentences are computed from the table. JSON gains `spread.current_regime.stress_spread` (MEASURED, n) and `spread.current_regime.all_minutes` |
| `tests/test_hurdle.py` | 4 new tests; 34 of 34 pass |

New stress hurdles: 5min **63.07%**, 1h **53.71%**, 6h **51.48%**, overnight 52.81% long / 51.64% short, 5d 53.40% /
50.57%. Against your assumptions, the 5-min stress hurdle falls 26.4 pp: 13.3 pp from volatility and 13.1 pp from the
spread (with your 8-pt stress spread and measured sigma it would be 76.1%). All 21 rows equal my independent
recomputation (0.00 pp; `rv_hurdle.py`, using the 2.0 measured from raw ticks).

The outputs were regenerated by re-running the pipeline at 14:36 server time from the warm cache. Apart from the fix, only
live-data drift changed: 5-min sigma 28.694 → 28.702 (N +1, today's first block), swap 5.08% → 5.066% p.a. (price), and
the gap and schedule counts (today's minutes). F3–F14 are still open.

**2026-10-05: F3, F4 and F8 fixed; your answers built in.** Your answers: Pro account, no commission, no swap. They are
stored in `config.py` (`ACCOUNT_TYPE`, `COMMISSION_RT_USD_PER_LOT`, `SWAP_CHARGED`; `AUDIT_COMMISSION_RT_USD` and
`AUDIT_SWAP_CHARGED` override them if the terms change). A new provenance tag, **USER-CONFIRMED**, marks values stated by
the account owner rather than measured.

| finding | change | result |
|---|---|---|
| F3 | `t6_vol.py`: P(T) = open at T, else the close of the last bar that started ≤ 5 min before T (past-only), else drop. Every year now shows `N_candidates` and `N_dropped`; samples ending after the data are not counted; dropped samples are listed in `out/sigma_dropped_samples.csv` | Overnight N/σ: 2021 25/78.4 → **192/91.6**; 2023 62/81.2 → **196/93.2**; 2025 190/152.6 → **196/173.9**. 5d 2021 N 5 → 45. Hurdle inputs unchanged (overnight 12m 228.52; 5d 661.46) or tiny (5-min 28.702 → 28.709, mostly the live session). The remaining drops are US holidays and half-days (Thanksgiving, Christmas, New Year, MLK, Presidents', Good Friday, Memorial, Juneteenth, 3 July, Labor Day) |
| F4 | `t1_coverage.py`: new gap kind "session shift after a DST change" (50–70 min, runs to the daily break, ≤ 21 days after a US or EU change; the DST dates come from the tz database). New calendar `out/session_shortened_days.csv` (91 shortened days) and a report table | 16 session-shift days: 2021-11-08..11, 2022-03-28..30, 2023-03-27, **2024-11-04** (the review had missed this one), 2025-03-31..04-08 |
| F8 | Commission comes from the user-confirmed config value (0), labelled USER-CONFIRMED; the deal history is kept as a MEASURED cross-check | Commission 0 in every hurdle row, as before, now with the right label |
| swap | `run.py`: swap = 0 when not charged; long and short rows collapse into one `n/a` row; the report and JSON state "not charged (USER-CONFIRMED)" | Overnight base 51.84% long → **50.66%**; stress 52.81% → **51.64%**. 5d base 53.07% long → **50.23%**; stress 53.40% → **50.57%** |

Tests: 8 new (`test_vol_price.py`, `test_gaps.py`, plus one in `test_hurdle.py`); 42 of 42 pass. Outputs were
regenerated with the pipeline at 14:51 server time. Still open: F5, F6 (partly: `spread.before_2021_08` still reads
MEASURED/null), F7, F9 (wording only; it no longer affects costs), F10–F14.

---

## Appendix A. Checklist

| item | result | note |
|---|---|---|
| A1 no trading calls | PASS | only initialize, terminal_info, account_info (server/currency/leverage/mode), symbols_get, symbol_select, symbol_info(_tick), copy_rates_*, copy_ticks_*, history_deals_get (aggregated), shutdown |
| A2 credentials redacted | PASS | no login, name, balance or password in code, outputs, log or cache. Aggregated deal counts per symbol appear in §3 (account activity, not credentials) |
| A3 no strategy/ML; cache ignored; nothing staged | PASS | no commits exist; `git diff --cached` is empty; `audit/cache/` is ignored |
| B1 timestamp interpretation | PASS | UTC-labelled datetimes passed to MT5, no double shift; live tick − UTC = 3,599.72 s |
| B2 open detection not circular | PASS | 7 hypotheses including 16:30 (NY-close). My unconstrained search agrees |
| B3 DST mismatch weeks shown; offset table matches DST dates | PASS | all US 2nd-Sunday-March / 1st-Sunday-November and EU last-Sunday weeks present 2019–2026 |
| B4 tests cover transitions and pass | PASS (with gap F12) | 30/30 pass; saved clock untested, but equals my model on every bar |
| B5 buckets labelled with the correct clock | PASS | server tables are exactly the ET tables shifted 5 h in the current regime (same tick_N) |
| C1 units | PASS | verified live and on raw ticks |
| C2 LOCF correct | PASS | ≤5-min carry, no carry across break or weekend, bid/ask ≤ 0 dropped before LOCF; full-LOCF variant differs by 29 of 39,686 minutes with identical percentiles |
| C3 percentiles over minutes with N | PASS (with F11) | |
| C4 rollover and events | PASS (with F9) | events APPROXIMATE (detected empirically), no invented dates |
| C5 bar spread bias quantified | PASS | equals the in-minute min in 99.75% of bars; not used for stats |
| C6 plausibility | PASS | 1.43 pts is plausible for a retail/pro US100 CFD; live quote = tick history |
| D1 swap_mode enum and formula | PASS | 0 = DISABLED; POINTS reading INFERRED, labelled |
| D2 conversion to pts/night | PASS | −4.2893 |
| D3 triple day, short sign | PASS | Friday; short 0 = neither pays nor receives |
| E1 earliest checked by more than one call; non-contiguity | PASS for bars; ticks PASS on numbers, FAIL on the claimed method (F5) | |
| E2 gap exclusions; top 20 plausible | PASS (with F4) | |
| E3 outliers past-only | PASS | `rolling(120, min 60).std().shift(1)`; first window NaN, not flagged |
| E4 roll conclusion supported | PASS | numeric demo, INFERRED, moderate confidence, limitation stated |
| E5 bar vs tick on overlap, bid-based | PASS | |
| E6 forming bar dropped | PASS | |
| F1 horizon definitions | PASS (with F3) | |
| F2 hurdle recomputed | PASS | 0.00 pp; slippage labelled ASSUMED |
| F3 comparison statements | FAIL at stress (F2) | base PASS |
| G1 labels truthful | PASS (with F6, F7, F9) | |
| G2 report = JSON = summary | PASS (with F9 wording) | no numeric mismatch found |
| G3 UNKNOWNs reported | PASS (with F8) | commission 0 is used in the hurdles despite n=1 |
| G4 sufficiency conclusion | PASS on numbers, MINOR overstatement (F14) | |
| H independent verification | PASS (pipeline rerun: CANNOT VERIFY) | |

## Appendix B. Reviewer files

`audit/review/rv_common.py` (connection and clock model) · `rv_live.py` (symbol, swap, offset, extents, earliest tick,
cache vs live, bars vs ticks) · `rv_time.py` (open step, FOMC, re-open) · `rv_clock_vs_helper.py` · `rv_spread.py` ·
`rv_vol.py` · `rv_gaps.py` · `rv_hurdle.py`. Outputs: `audit/review/out/*.json`, `rv_hurdle.csv`. Each script takes a
scratch folder for raw pulls: `python audit/review/rv_live.py <scratch>` first, then the others.
