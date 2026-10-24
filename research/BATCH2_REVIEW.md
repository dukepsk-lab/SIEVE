# Batch 2 review (orchestrator)

Reviewed 2026-10-05. Batch 2 was pre-registered in `PLAN.md` §9 before any result existed. Two Sonnet 5.5 agents built
the events file (`research/data/`) and the code (`variants2.py`, `inference.py`, `run_batch2.py`); results are in
`out/RESULTS_BATCH2.md`. This note records the orchestrator's checks and the gate decision.

## Checks

| check | result |
|---|---|
| Tests | 106 pass (27 batch-1 research, 37 batch-2, 42 audit). The agent broke the code on purpose 15 times and the tests caught every one. Batch-1 outputs are byte-identical after the change |
| Events file provenance | Every date is parsed from saved official pages (`data/events_sources/`): Fed calendar, historical and statement pages; BLS news-release archives and yearly schedules, captured through a browser because BLS blocks scripts. CPI and NFP dates are cross-checked archive ↔ schedule. The shutdown delays are recorded as actually released, and the cancelled October 2025 releases are omitted |
| Events file against the bars | Median range ratio at the event minute: CPI 20.5, NFP 16.3, scheduled FOMC 10.3. All 13 FOMC dates independently confirmed by 14:00-ET spikes in the audit review are present. The low-ratio flags cluster in 2019–2020 CPI releases (low sensitivity then), not in date errors |
| Version used | The coder ran against events.csv `fb9c2479…`, which is the final file |
| Independent recomputation (own clock model, live bar pull, separate code) | H3a A: N 35, 44.80 bp, t 2.24; H3a B: N 16, 23.41 bp, t 0.90; H8a A: N 135, 14.93 bp, t 1.01. **All identical.** H6a: A alpha 3.71 bp/day, t 2.23 (agent 3.55, 2.12); B alpha 1.41, t 0.72 (agent 1.40, 0.72). The small Stage A difference comes from cost-booking conventions at the window start; **the gate verdicts are the same** |

## Gate decision

| variant | Stage A (2019-07 → 2023) | Stage B (2024–2025) | outcome |
|---|---|---|---|
| H6a vol-managed, cap 2 | alpha t 2.12, Sharpe 1.10 vs 0.75 → pass | alpha t 0.72, Sharpe 1.17 vs 1.09 → **fail** | stop |
| H6b vol-managed, cap 1 | alpha t 1.72 → fail | (not run) | stop |
| H3a pre-FOMC drift | t 2.24, 35 events → pass | t 0.90, 16 events → **fail** | stop |
| H8a announcement-day premium | t 1.01 → fail | (not run) | stop |
| H8b 08:30-release overnight | t 0.16 → fail | (not run) | stop |

**No batch 2 variant survives. The 2026 holdout stays locked.** The plan allows Stage C only for Stage B survivors, so
neither near-miss may use it. **13 variants tested so far.**

## Reading

- **H6a and H3a pointed the same way in validation but were not significant.**
  - H6a still beat buy and hold on Sharpe in 2024–25 (1.17 vs 1.09).
  - H3a was positive in both validation years.
  - The samples are too small to separate this from luck: 16 FOMC events, and two years of alpha at about 1.4 bp/day.
- **H6a's Stage A pass is leverage on drift.** It sat at the 2× cap in the calm, rising years 2019, 2021 and 2023. That is
  a known property of volatility-scaling, not a market-timing edge.
- **Announcement days (H8a) are not reliably better than other days (E0):** +9.2 bp per trade, Welch t 0.58.
- **Across both batches, the only consistent return source is long market exposure.** No pre-registered timing or event
  rule clears costs and the validation gate on this data.

## Notes for any future work

- **Delayed releases:** using actual release dates is fine for trading, because BLS announces rescheduled dates in advance.
  A forward test should still log the date that was announced at the time.
- **Do not re-test these 13 variants or their mirrors on 2019–2025 data.** A fair test of H6a or H3a now needs data that
  no one has looked at: forward observation from 2026-10-05 onward, pre-registered before it starts. The 2026 holdout
  cannot be used for them.
