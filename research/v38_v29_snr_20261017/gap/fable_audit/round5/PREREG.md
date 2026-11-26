# Round 5 PREREG — 大波動日收緊出場 (XT) — written 2026-11-21 ~01:00 BEFORE any run
User idea: 當日已大跌(大漲)時不出場、但收緊出場條件（漲跌幅上限 10% → 剩餘空間有限）；同樣問多單急漲時。

Prior evidence seen before writing (disclosed):
- V049 (exploratory, WRONG question = exit immediately at X%): hold beat immediate exit for shorts at X=4/5/6/7%; longs ≥5% only 1 day since 2020.
- report.md: v30e 2024+ profit is concentrated on big down days (synthetic put); tightening on those days attacks the profit source. Prior: likely FAIL.
- Event counts (day-session-close ref): ≤−4%: 33 days (21 in 2024+), ≤−6%: 11 (8). Longs ≥+4%: ~6 days.

Rule (Pine-implementable): at each completed 5m close, with ref = previous trading day's day-session (13:45) close (_ST["prev"]),
if a position is open and (close/ref − 1)·direction ≥ X% → ARM (until flat). While armed: best = most favourable close since arming;
extra stop for ALL open lots at best − k·baseATR (long) / best + k·baseATR (short); combined with existing stops taking the tighter. Reset when flat.
Symmetric for longs and shorts. Base = NOBE (live-like). Variants: XT3_1, XT3_2, XT4_1, XT4_2, XT6_1, XT6_2 (X% _ k ATR) × 4 offsets = 24 runs.
Data: mxf_1min extended to 2026-11-21 05:00 (validated: overlap with mxf_1min_2020_20261111.csv identical; NOBE trades before 2026-11-11 identical to round-4 NOBE).
Note: extended data adds ~7 trading days incl. 11/16, 11/20 crash days → base numbers differ from round 4; all comparisons are within round 5.

Scoring: standard five-condition rule vs NOBE, with pre-set adjustments because the rule rarely fires:
- cond 4 (2020–23 better ≥3/4 offsets): offsets with zero difference count as "not worse" (tie passes).
- cond 5 (ex-top-10 days) is reported but NOT used as a veto (the effect lives on extreme days by construction).
Also reported: event table (per armed trading day, cost-adjusted Δ vs NOBE, mean over offsets), hit count of days helped / hurt, split by side.
Long side: reported separately; if long armed days < 10 it is stated as "cannot be validated" (no verdict).

---
# Addendum 1 (2026-11-21 ~01:40, user follow-up, written AFTER seeing V050 FAIL, BEFORE running these)
User: 改成「連續大跌」或「距離月線/某均線乖離過大」時收緊出場？ Same XT mechanics (arm → all lots get best-close ∓ k·baseATR trail; reset flat), different arm trigger,
measured at each 5m close vs previous trading days' day-session closes (_ST["closes"], today excluded from MA):
- R3_X_k:   (close / close 3 trading days ago − 1)·dir ≥ X%,  X ∈ {4, 6}
- MA20_X_k: (close / MA20 − 1)·dir ≥ X%,  X ∈ {5, 8}
- MA60_X_k: (close / MA60 − 1)·dir ≥ X%,  X ∈ {8, 12}
k ∈ {1, 2}. Thresholds chosen from FREQUENCY ONLY (≈5% / ≈2% tail of daily values since 2020; no P&L looked at for these triggers).
Prior: V050 says tightening on crash days cuts the profit source; these triggers overlap crash regimes → prior is FAIL.
12 variants × 4 offsets = 48 runs; same scoring as round 5. Multiple-testing note: with V049/V050 this family is now 19 variants.
