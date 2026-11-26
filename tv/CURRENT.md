# V38 目前版本（2026-11-26）

- **實盤上線中**：`TF_V38_v30e_stage2.pine`（V38.1126_v30e_STAGE2 Session）= v30e + LB7S / LL5 / S24 / NS5 / SAT1 / BDL1，本金 1,000,000、手續費 380/口
- `TF_V38_v30e_stage2b.pine`：同 STAGE2 交易邏輯，只加儀表板大小/位置/精簡/隱藏選項
- `TF_V38_v30e.pine`：上一個實盤版（V38.1106_v30e）；`TF_V38_v30e_1m.pine` 只把本金改 100 萬供比較
- `TF_V38_v30e_lb7*.pine`：STAGE2 的中間版本（逐條加規則）
- `TF_V38_v30/v30b/v30c/v30d/v30f*.pine`、`v28`、`v29`：歷史研究版本
- `generators/`：產生上述 Pine 的 Python 腳本（字串替換），重產 STAGE2 需依序跑 mk_v30e_stage2.py → fix_stage2_dashboard.py → 本金改 1,000,000
- `result/V38.1126_v30e_STAGE2_*.csv`：STAGE2 的 TradingView 回測匯出
