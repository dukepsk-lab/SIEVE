# Stage A review (orchestrator)

Reviewed 2026-10-05. The code and runs (`research/*.py`, `research/out/`) were produced by a Sonnet 5.5 agent from
`PLAN.md`. This note records the orchestrator's checks and the gate decision.

## Checks

| check | result |
|---|---|
| Tests | 27 research tests and 42 audit tests pass. The agent broke the code on purpose four times (same-day H2 signal, late H4 gap, unlagged H5, ignored H1a next-day check) and the tests caught each one |
| Spec compliance and lookahead (read `variants.py`, `data.py`, `evaluate.py`) | H2 enters at 15:31, after its 15:30 input; H4's σ is shifted before the rolling window; H5 uses a one-day-lagged signal; holdout bars are dropped at load time and the evaluator refuses 2026 dates. No deviation from PLAN §2–§4 |
| Independent recomputation (own clock model, live bar pull, separate code) | H1a: N 872, gross 7.01 bp, net stress 4.97, t 1.59. C1: N 1,096, 3.92, 1.88, 0.50. H2a: N 1,051, −0.92, −2.96, −2.17. **All identical to the agent's output** |

## Gate decision

**Stage A: 0 of 8 candidates pass. Stage B has nothing to run. The holdout (2026) stays locked and untouched.**
The multiple-testing count is now 8.

## What the numbers say (development period 2019-07 → 2023, stress costs)

- **The only positive returns come from being long in a rising market.**
  - Overnight-only longs (H1a: t 1.59, Sharpe 0.74) earn more per day than the intraday half (C1: Sharpe 0.23), as the
    overnight-premium idea predicts. But H1a's Sharpe is the same as plain buy and hold (C2: 0.75).
  - Long/flat momentum (H5b: t 1.84, Sharpe 0.86) is mostly buy and hold minus most of 2022.
  - None of these reaches t 2. None is a timing edge that is distinct from market exposure.
- **Intraday momentum (H2a) went the wrong way, with t −2.17.** The last half hour tended to reverse the morning move.
  - Flipping the rule now would be a new, post-hoc variant.
  - Even the flip grosses only +0.92 bp against a 2.03 bp stress cost, so it is not tradable.
- **Fading opening gaps (H4) lost.** Their mirror, continuation, is a post-hoc idea whose gain is dominated by 2020 (fade
  −2,322 bp that year vs at most ±805 bp in the others). It would not count as evidence.
- **Power reminder:** t ≥ 2 over 4.5 years needs an annual Sharpe of about 0.94. Effects of the size reported in the
  literature for these anomalies (Sharpe 0.3–0.7) are below what this sample can confirm.

## Implications for the next batch (not pre-registered yet)

1. **A timing edge from price alone at intraday horizons is not evident** at this broker's stress cost (2.03 bp per round
   trip) on this sample.
2. **Risk-managed long exposure is a different question from alpha.** For example, volatility-scaled exposure is designed
   to improve the Sharpe of the equity premium; it needs its own pre-registration and its own benchmark (C2).
3. **Event-based hypotheses** (pre-FOMC drift, CPI and NFP releases) need a real events file from the official calendars,
   and their small N limits power.
4. **Every new variant raises the Bonferroni bar.** Post-hoc mirrors of failed variants (H2 fade, H4 continuation) should
   not be added.
