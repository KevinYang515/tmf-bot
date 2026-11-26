# Round 8 / V061 PREREG — 加碼單風險控制（2026-11-25，寫於任何回測之前；使用者要求「多探索」→ 視為探索族群）
同資料 shadow_gates/mxf_1min_live.csv（至 2026-11-24 05:00），基準 NOBE（沿用 round7 同資料結果），4 offsets。
變體：
- ML2 / ML3：opt_max_lots = 2 / 3（2=最多1次加碼、無G；3=最多2次加碼、無G）。現行 4 = 2次加碼+G。
- NX：夜盤 04:40 之後禁止新加碼，且 04:45~04:55 收盤的 bar 觸發平掉所有 Add 單（下一根開盤成交，仍在夜盤）。目的：避開夜→日跳空穿停損。
- NXG：同 NX，另含 G 單。
- ABE1 / ABE2：opt_add_be_trigger = 1.0 / 2.0（加碼單浮盈 > 自身進場ATR×k 後停損移到成本）。
評分同 round6/7：PASS 全部滿足 (1) 平均RR24 ≥1.10×基準 (2) RR24 ≥3/4 offset 較佳 (3) 平均net24 ≥0.85×基準 (4) RR23 ≥3/4 offset 不差。
ML2/ML3 為部位大小，預期 (3) 失敗；只看 RR。總嘗試數連同 round7 = 9 變體 → 任何 PASS 都需要再過 Fable 審查與 walk-forward 才可談上線。
