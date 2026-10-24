# SIEVE

Data-integrity, cost and pre-registered hypothesis testing on US100 (`USTEC.`, IUX Pro, MetaTrader 5).

Most intraday backtests go wrong before any model runs: clock, DST and spread assumptions. SIEVE measures those first, then tests ideas under a protocol fixed in advance, and reports what fails.

## Phases

| phase | what | where |
|---|---|---|
| 1. Audit | Read-only measurement of the data and broker conditions: server clock (UTC → London, era-aware), tick-level spread regimes, session changes, integrity checks, volatility and break-even hit-rate hurdles. Every value is tagged MEASURED / INFERRED / ASSUMED / USER-CONFIRMED with N. | [`audit/`](audit/README.md), [`audit/report.md`](audit/report.md) |
| 1b. Independent review | A second implementation re-derives every headline number from raw data (`rv_*.py`). Verdict and fixes are logged. | [`audit/review/`](audit/review/REVIEW.md) |
| 2. Hypotheses | Edge hypotheses and pass/fail gates frozen in [`research/PLAN.md`](research/PLAN.md) **before** any result was computed. Development period 2019-07 → 2023 (Stage A), validation 2024–2025 (Stage B), 2026 holdout locked. Changes after seeing results count as new variants for multiple-testing correction. | [`research/`](research/) |

## Results (as recorded in the review notes)

- **Stage A:** 0 of 8 candidates pass; Stage B not run; holdout untouched ([`STAGE_A_REVIEW.md`](research/STAGE_A_REVIEW.md)).
- **Batch 2** (pre-registered events: CPI, NFP, FOMC; vol-managed exposure; pre-FOMC drift): near-misses in Stage A fail in Stage B; no variant survives ([`BATCH2_REVIEW.md`](research/BATCH2_REVIEW.md)).
- The only positive returns found are long exposure to a rising market, indistinguishable from buy and hold.

None of the tested ideas worked. This covers one instrument, one broker, and only the variants and costs listed in the plan.

## Method

- Costs are measured spread plus assumed slippage, in index points; stress cases use the widest quote of the regime.
- Time-of-day statistics go through an era-aware `ServerClock` (tested across DST transitions).
- Lookahead guards: signals lagged or entered after their inputs; holdout dates rejected by the evaluator; tests are mutation-checked (code deliberately broken, tests must fail).
- Raw broker data is never committed (cache is gitignored); only small derived tables live in `audit/out/` and `research/out/`.

## Reproduce

Requires Windows, Python 3.10+ and a logged-in MT5 terminal for the audit (`pip install MetaTrader5 pandas numpy pyarrow tzdata pytest`).

```
python -m audit.run
python -m pytest audit/tests research -q
```
