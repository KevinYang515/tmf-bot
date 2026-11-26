# PREREG — Round 4 (written 2026-11-17 BEFORE any round-4 engine run)

Baseline, data, offsets, cost model, pass rule: identical to round 3 (`round3/PREREG.md`): v30e standalone, `mxf_1min_2020_20261111.csv`,
offsets 0–3, cost R, primary window 2024-01-01→2026-11-11, robustness 2020-03→2023, five-condition rule. Base = round3 `eng_fable/base_off*.csv` (copied).

## L_MA — no LONG Cmd in a bear regime (3 variants)
At each completed 5m signal bar, P = close of the previous trading date (same trading-date definition as T1 in round 3: night session belongs to next date),
MA_N = simple mean of the last N trading-date closes up to and including P. A LONG Cmd is not queued when P < MA_N. Adds/G/shorts untouched
(Adds can only follow a filled Cmd, so the whole long campaign is skipped). Known before running.
- L_MA20 [primary]   - L_MA10   - L_MA60   (plateau check)
Hypothesis: counter-trend long probes below the monthly average have negative expectancy.
Disclosure: before writing this I saw a campaign-level table on the baseline trade list, 2024+ only: long campaigns when prev close < MA20: n=60, −8.1萬 total (avg −0.14萬);
same regime shorts +181.5萬. I did NOT look at 2020–23 for this split. Because the rule was chosen after an in-sample (2024+) look, the best verdict is OBSERVE
unless 2020–23 (condition 4) also holds AND all other conditions pass, in which case it is reported as "PASS (post-hoc, 2024+ seen)" — still freeze-and-shadow only.
Known risk: V-shaped rebounds (e.g. 2025-04, 2026-11-09~11) start below MA20; blocking them may cost the big long winners.

## NOBE — engine fidelity check (1 variant, not a candidate rule)
Disable the Cmd break-even stop as an exit (BE arming for the short pyramid cap unchanged). Reason: 2024-01→2026-11-05 TV v30e export shows L_BE 6 / S_BE 11 exits,
the engine shows 29 / 25 on the same period, and on 2026-11-13 the engine exited the long Cmd at BE (10:20) while TV held to L_Exit 44110 (11:13).
Question: is the engine's BE stop optimistic vs TV, and how much does it move the baseline? Reported, no verdict.

Planned runs: 4 variants × 4 offsets = 16. Any follow-up gets an addendum here BEFORE it is run.

---
# Addendum 1 (2026-11-17, written AFTER the runner printed full-period raw pnl totals per run, BEFORE running the cost-R/pass-rule summary)
Evidence on BE: in the TV v30e export, BE exits happen only when BE arms on the Cmd entry bar itself (9/22 such trades); when it arms on any later bar (342 trades) TV never exits at BE.
Consistent with Pine exit-quantity reservation (L_Exit issued first reserves the whole entry; a later L_BE gets 0). So NOBE is the closer model of live.
- L_MA20_NOBE: L_MA20 on the NOBE engine, scored against NOBE as the base (primary reading of the MA20 idea for live). 4 offsets.

---
# Addendum 2 (2026-11-17, user idea, written BEFORE running): campaign-level break-even ("獲利到一定/滿倉有獲利 → 開保本")
Base for scoring = NOBE (live-like). Armed at a completed 5m close when the condition holds; once armed (until flat) every open lot gets an extra stop at the CURRENT
average entry price of the open lots (recomputed each bar; whole remaining position exits together ≈ campaign scratch on open lots). Fills next bars intrabar like other stops.
- CBE_F1: position full (short 4 lots / long 3 lots — long G disabled in v30e) AND (close − avg)·dir ≥ 1.0 × baseATR
- CBE_F2: position full AND (close − avg)·dir ≥ 2.0 × baseATR
- CBE_P2: any position with ≥ 2 lots AND (close − avg)·dir ≥ 2.0 × baseATR
Prior related result: per-lot Add profit protection ("加碼保利") was tested before and rejected (memory note); this is campaign-level, not per-lot. Thresholds picked a priori, not from data.
Known risk: trend campaigns that pull back to the average before resuming get cut (the big winners are what pay for everything).
Same five-condition rule; 3 variants × 4 offsets.
