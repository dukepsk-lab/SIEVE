# Phase 2: edge hypotheses and test protocol (pre-registered)

Written 2026-10-05, before any strategy result was computed. The rules, variants and pass/fail gates below are **frozen**.
Any change after results are seen must be logged in §8 with the reason, and it counts as a new variant for the
multiple-testing correction.

## 1. Inputs from the audit

| input | value | source |
|---|---|---|
| Instrument | `USTEC.` (IUX Pro, MT5), M1 **bid** bars, 2019-07-16 → 2026-09 (cache) | `audit/cache/rates/USTEC/M1/*.parquet` |
| Clock | server → New York via `audit.tz.ServerClock.load("audit/out/server_clock.json")` | audit task 4 |
| Round-trip cost, base | spread 1.43 + slippage 2 × 0.5 = **2.43 pts** | `cost_model_inputs.json`: spread p50, slippage (ASSUMED) |
| Round-trip cost, stress | spread 2.0 + slippage 2 × 2.0 = **6.00 pts** | `spread.current_regime.stress_spread`, slippage (ASSUMED) |
| Commission, swap | 0, 0 | USER-CONFIRMED 2026-10-05 |
| Shortened sessions | 91 days, including 16 DST session shifts | `audit/out/session_shortened_days.csv` |

**Costs in basis points.** The edges tested here are percentage effects, and the question is whether they beat
*today's* cost, so costs are applied in bp of notional: `cost_bp = cost_pts / P_REF × 1e4`. P_REF is the mean M1 close over
the current spread regime (2026-05-14 → 2026-10-04), about 29,495, which gives **base 0.82 bp and stress 2.03 bp per round
trip**. Sensitivity: the same point costs divided by each trade's entry price, which is harsher in early years when the
price was 8,000–15,000.

## 2. Price and timing conventions

- **Trading day** d = an ET weekday with at least one bar. **Previous trading day** d−1 = the latest trading day before d.
- **P(T)** = open of the M1 bar stamped T (ET). If there is none, use the close of the last bar stamped before T, but only if
  that bar started at most 5 minutes earlier. Otherwise P(T) is missing and the trade is **skipped** and counted, never
  filled. This is `audit.t6_vol.price_at`.
- Bars are bid. A long pays the spread on entry and a short pays it on exit; the round-trip cost covers both.
- **No lookahead:** every signal uses only prices stamped strictly before the entry time, or the open at a time that is
  earlier than the entry time.

## 3. Hypotheses and frozen variants

Priority goes to effects that are documented for US equity indices and have an economic reason to persist. They are
**hypotheses**: the audit says nothing about whether they work on this CFD.

### H1: overnight risk premium
*Rationale:* in US index products, much of the equity premium has historically accrued outside cash hours, for example as
compensation for holding risk when hedging is hard, or because opening order flow is one-sided. With **no swap** on this
account, holding a long overnight costs nothing beyond the round trip.
- **H1a**: long P(16:00, d) → P(09:30, d+1), entries Monday–Thursday; skipped if d+1 is not the next calendar weekday.
- **H1b**: long P(16:00, Friday) → P(09:30, Monday); skipped if Monday is not a trading day.
- *Controls, reported only, not candidates:* **C1** long 09:30 → 16:00 every day (the intraday half), and **C2** buy and hold
  over the period (one round trip).

### H2: intraday momentum (first half hour → last half hour)
*Rationale:* the return from the previous close to 10:00 ET has been reported to predict the last half hour's return in US
index ETFs. Proposed mechanisms are late-day hedging by option dealers and informed traders who trade late.
- r1(d) = P(10:00, d) / P(16:00, d−1) − 1; r2(d) = P(15:30, d) / P(15:00, d) − 1.
- **H2a**: direction = sign(r1). Entry P(**15:31**, d), one minute after the last signal input; exit P(16:00, d).
- **H2b**: trade only when sign(r1) = sign(r2) ≠ 0; that direction; same entry and exit.

### H4: opening-gap reaction
*Rationale:* large overnight gaps may overshoot (dealers provide liquidity into the open, so the move fades) or under-react
(the move continues). The prior is **fade**.
- g(d) = P(09:30, d) / P(16:00, d−1) − 1. σ_g(d) = standard deviation of g over the previous 60 trading days with a valid g
  (at least 40), excluding d. z = g / σ_g.
- **H4a**: when |z| ≥ 1.0, direction = −sign(z); entry P(09:35, d), exit P(16:00, d).
- **H4b**: the same with |z| ≥ 1.5.
- Continuation is the mirror trade (gross P&L × −1, cost still charged); it is reported but not tested separately.

### H5: time-series momentum (daily)
*Rationale:* trend persistence in index returns, from slow diffusion of information and from hedging flows. It trades
rarely, so it is the least cost-sensitive variant, but on a single index the expected Sharpe is low.
- C(d) = P(16:00, d). m(d) = C(d) / C(d−60) − 1, counting 60 trading days with a valid C.
- Position held from C(d) to C(d+1) = f(m(d−1)), a **one-day lag**.
- **H5a**: f = sign (long or short). **H5b**: f = 1 if m > 0, else 0 (long or flat).
- Cost: each unit change in position costs half a round trip, so a flip from +1 to −1 costs one full round trip.

### Deferred
- **H3, pre-FOMC drift** (long from 14:00 ET the day before an FOMC statement until 13:55 on the day). It needs a real events
  file built from the Federal Reserve's published calendar, and with about 8 events a year it has little power.
- **Volatility-scaled sizing.** This is a sizing layer, not an edge; it comes later if a candidate survives.

**8 candidate variants**: H1a, H1b, H2a, H2b, H4a, H4b, H5a, H5b. The multiple-testing count starts at 8.

## 4. Periods and gates

| stage | entry dates | what is allowed | pass gate (stress costs) |
|---|---|---|---|
| A: development | 2019-07-16 → 2023-12-31 | all 8 variants, frozen rules | net mean > 0, **t ≥ 2.0**, and ≥ 3 of the 5 calendar years net positive |
| B: validation | 2024-01-01 → 2025-12-31 | only Stage A survivors, no changes | net mean > 0 and **t ≥ 1.5** |
| C: holdout | 2026-01-01 → end of data | **locked**; only B survivors, only after the user approves | reporting only |

- **t-statistic:** daily net P&L series in bp over every trading day of the period (0 on days without a position);
  t = mean / std × √N_days, which equals the annualised Sharpe × √years. P&L is booked on the entry day.
- **Final evidence standard** (after C): t ≥ 3.0 over A+B+C with stress costs, *and* one-sided p < 0.05 / (number of
  variants evaluated in Stage A), i.e. a Bonferroni correction.
- **Power:** Stage A covers about 4.5 years, so t ≥ 2 needs an annual Sharpe of about 0.94 or more. Stage B needs about 1.06.

## 5. Metrics reported per variant and stage

trades, trades per year, skipped trades (missing price, shortened session); mean gross and net bp per trade (base, stress,
point-cost sensitivity); annualised Sharpe and t (stress); hit rate (stress); max drawdown of cumulative net bp (stress);
net bp and sign per calendar year.

## 6. Guards

- The evaluation code **refuses** to score any trade that enters on or after 2026-01-01 unless it is explicitly unlocked.
  Only the user can authorise Stage C.
- Rolling inputs (σ_g, m) may use earlier periods' data (that is past data); they never use later data.
- No parameter search beyond §3. No ML in this phase.

## 7. Roles

Design, review and gate decisions: Opus 5.5 (orchestrator). Code and runs: Sonnet 5.5 subagents, working from this plan.

## 8. Change log

- **2026-10-05: batch 1 Stage A finished**, with 0 of 8 passing (`STAGE_A_REVIEW.md`). The batch 1 rules were not changed.
- **2026-10-05: batch 2 pre-registered (§9)** before any batch 2 result was computed. The user chose its two directions:
  risk-managed long exposure and event-based effects. It adds 5 variants, so the **multiple-testing count rises to 13**.
  Batch 1's failed variants are not revisited, and no post-hoc mirrors are added.
- **2026-10-05: batch 2 finished** (`BATCH2_REVIEW.md`). H6a and H3a passed Stage A and failed Stage B; the other three
  failed Stage A. No survivor, so the holdout stays locked. 13 variants tested in total.
- **2026-10-05 (11:30 New York time): forward test pre-registered (§10)** for H6a and H3a, at the user's request. It is
  paper only, and its rules were fixed before the forward window started.

## 10. Forward test of H6a and H3a (pre-registered 2026-10-05, before the window starts)

**What:** paper-track the two batch 2 near-misses on data that did not exist when they were designed. Nothing is traded
and no order function is ever called. The rules of §9 are applied **unchanged**.

- **Forward window:** entries on or after **2026-10-06** (New York trading day).
  - Prices before that date may be used **only as inputs** (H6a needs the previous 20 returns).
  - No P&L or statistic is ever computed for 2026-01-01 → 2026-10-05; that holdout stays locked.
  - Positions start flat: H6a enters at C(2026-10-06) and pays the entry cost then. C2 (buy and hold) is tracked from the
    same close as H6a's benchmark.
- **Data:** USTEC. M1 bars pulled read-only from MT5 on each run. Clock: `server_clock.json`. The tracker checks the live
  offset against the clock on every run and **halts** if they disagree.
- **Events for H3a:** scheduled FOMC statement dates on or after 2026-10-06, parsed from the official Federal Reserve
  calendar page saved on 2026-10-05 (`data/events_sources/fed_fomccalendars.html`). If the Fed changes its calendar, the
  page is re-captured and the change is logged here. Unscheduled meetings are excluded.
- **Costs:** the frozen §1 stress cost (6.00 pts, 2.03 bp) is primary, with base reported alongside. The live quoted spread
  is logged on each run as a diagnostic; if the broker re-prices above the 2.0-pt stress spread, it is reported here.
- **Runs:** at any time after 16:05 New York time on a trading day. Each run recomputes everything from the bars, so it is
  stateless and a missed day catches up. Each run also appends a timestamped snapshot to an append-only log; committing
  that log to git periodically makes it tamper-evident.
- **Decision rules: no interim decisions and no early stopping.** Monthly reports are descriptive only.
  - **H3a**, at the 24th scheduled forward FOMC event (about 3 years): pass if the forward net-stress mean > 0 and the
    forward t ≥ 2.0. The t is the daily series over the forward window, as in §4. The threshold comes from two forward
    hypotheses on fresh data: one-sided α 0.025, so t ≈ 1.96.
  - **H6a**, at 756 forward trading days (about 3 years): pass if alpha vs C2 > 0 with Newey-West(5) t ≥ 2.0, and
    Sharpe(H6a) > Sharpe(C2).
- **Power warning, stated in advance:** at the effect sizes seen in validation, both checkpoints would most likely miss
  even if the effects are real. H6a's validation alpha t was 0.72 over 2 years; H3a's was 0.90 over 16 events. A fail would
  not prove the effects are absent; a pass would be strong evidence.

## 9. Batch 2 (pre-registered 2026-10-05)

Same data, costs, P(T), periods, holdout guard and metrics as §1–§6 unless stated otherwise.

### H6: volatility-managed long exposure
*Rationale:* volatility is persistent, but expected returns do not rise in proportion to it. Scaling equity exposure down
when recent volatility is high, and up when it is low, has been reported to raise the Sharpe ratio of the market
portfolio. This targets **risk-adjusted improvement over buy and hold (C2)**, not standalone alpha.
- C(d) = P(16:00, d) over valid closes (as in H5); r(d) = C(d) / C(d−1) − 1.
- σ̂(d) = std (ddof 1) of the last 20 valid daily returns up to and including d, × √252.
- Target exposure w*(d) = min(cap, σ* / σ̂(d−1)): a **one-day lag**, with σ* = **20% a year** (a fixed constant, not fitted).
- Position held from C(d) to C(d+1) = w, where w moves to w* only when |w* − w| ≥ 0.10 (a no-trade band). Each unit
  change in w costs half a round trip. Daily P&L in bp of capital = w × r(d+1) × 1e4 − cost.
- **H6a**: cap 2.0 (allows up to 2× exposure). **H6b**: cap 1.0 (only de-risks).
- **Gate.** Regress the variant's daily net bp on C2's daily net bp: OLS with Newey-West standard errors, 5 lags.
  - Stage A passes if alpha > 0 **and** the alpha t ≥ 2.0, Sharpe(H6) > Sharpe(C2), and the residual (variant − β × C2)
    sums positive in at least 3 of 5 calendar years.
  - Stage B passes if alpha > 0 and t ≥ 1.5.

### Event-based hypotheses
*Events file:* `research/data/events.csv` (event, date_et, time_et, scheduled, source_url, note), built **only from the
official calendars and release archives** of the Federal Reserve (FOMC statements, 14:00 ET) and BLS (CPI and Employment
Situation, 08:30 ET). It records **actual** release dates; these differ from the planned schedule when releases were
delayed, as in the October 2025 shutdown. It is checked against the bars: an event minute should show a range spike.
Unscheduled meetings (for example March 2020) are kept with scheduled = False and excluded from the variants below.

- **H3a: pre-FOMC drift.** *Rationale:* US index returns have historically been unusually high in the 24 hours before
  scheduled FOMC statements; later work reports the effect weakened. Long P(14:00, d−1) → P(13:55, d) for scheduled FOMC
  days d (d−1 = previous trading day).
- **H8a: announcement-day premium.** *Rationale:* investors demand a premium for bearing scheduled macro announcement
  risk, so returns on announcement days have historically exceeded those on other days. Long P(16:00, d−1) → P(16:00, d)
  for d in the union of scheduled FOMC, CPI and NFP days; a day with several events gets one trade.
- **H8b: 08:30 release, overnight capture.** The same premium for the pre-open releases. Long P(16:00, d−1) → P(09:30, d)
  for CPI and NFP days. The CFD trades through 08:30, so the release falls inside the hold.
- *Control (report only):* **E0**, the H8a trade on every non-event trading day. Report the mean difference between
  H8a and E0 and a Welch t-test.
- **Gate:** the same as batch 1 (net stress mean > 0, daily-series t ≥ 2.0, at least 3 of 5 years positive; Stage B
  t ≥ 1.5).
- **Power warning:** H3a has about 36 events in Stage A, so only a very large effect can reach t 2. H8a has about 140
  event days.

**Batch 2 variants:** H6a, H6b, H3a, H8a, H8b, making **13 in total**. Final evidence after Stage C requires t ≥ 3.0 over
A+B+C and one-sided p < 0.05 / 13, i.e. t of about 2.67 or more after the Bonferroni correction.
