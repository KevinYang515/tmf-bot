# V38 研究程式碼快照（2026-11-26）

來源：本機 `E:\stock\v38_research_repo`（commit 197a8da）匯出，路徑結構保持跟本機 `E:\stock\` 相同。

- `v38_v29_snr_20261017/`：V38 v29→v30e→STAGE2 的回測研究（gap/fable_audit round4~14 引擎、分析腳本、審查報告）
- `tmf_bot_ops/`：實盤機器人維運與歸因研究（加碼歸因、洗盤再進場、收腳/Λ、V 轉、對帳腳本）
- `research_registry/`：嘗試次數登記簿（trials.csv，供 DSR/PBO 用）

不含：實盤帳戶資料（餘額/成交/對帳 csv）、1 分K 行情資料、任何憑證。程式內路徑寫死 `E:\stock\...`，需在原本機目錄結構下執行。
