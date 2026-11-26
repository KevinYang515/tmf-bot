# Round 6 PREREG — 口數上限（波動調整 / 週末前夜盤）— written 2026-11-23 ~19:00 BEFORE any run
User approved "3 做 c" (test both). Context disclosed: idea (b) came AFTER seeing 2026-11-23 loss (4 lots short over weekend, Fri night close 33955 → Mon cover avg 35042, ≈ −21.7萬). So (b) is post-hoc → stricter bar.
Mechanics (Pine-implementable, only blocks NEW Add/G entries; never force-closes; Cmd entry always allowed = 1 lot):
- (a) VK_K: daily range r_d = (max − min of 5m closes in trading day)/prev day last close. ratio = mean(r last 20 days)/median(r last 250 days) (ratio=1 until 250 days). cap = max(1, floor(K/ratio)). Add/G allowed only if |posSize| < cap. K ∈ {4, 6}.
- (b) WK_c: during a night session whose next session starts > 24h later (Fri night / pre-holiday; calendar known in advance), Add/G allowed only if |posSize| < c. c ∈ {1, 2}.
- (c) C_K_2: VK_K + WK_2, K ∈ {4, 6}.
6 variants × 4 offsets. Base = NOBE re-run on the same data (mxf_1min to 2026-11-21 05:00).
Scoring (risk-adjusted, because a cap mechanically lowers P&L): per offset, from cost-adjusted daily net:
  RR24 = net 2024+ / |MDD 2024+| ; RR23 = net 2020–23 / |MDD 2020–23|.
  PASS needs ALL: (1) mean RR24 ≥ 1.10 × base (WK/C variants: ≥ 1.15 ×), (2) RR24 better on ≥ 3/4 offsets, (3) mean net24 ≥ 0.85 × base, (4) RR23 not worse on ≥ 3/4 offsets.
Reported only: worst day 2024+, weekend/holiday-gap P&L, lots-held distribution.
Prior: unknown; sizing ≠ exit-timing family (V049–V053).
