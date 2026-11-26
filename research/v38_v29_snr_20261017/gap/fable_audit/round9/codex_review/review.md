## 審查結論：SHADOW-ONLY

不得以 LB7 直接切換實盤。

- 引擎 LB7 在完成 5 分 K 後，以當根 close、現有持倉方向判斷；只注入 Add/G，Cmd、既有 lot 與出場不受限，無明顯前視。正負持倉符號處理正確。
- Pine 兩版均完整覆蓋四個 Add/G 分支，`>=7%` 與引擎一致；v5 語法看來可編譯。`time_close` 為 UNIX 時戳，時區函式可指定 Asia/Taipei。[TradingView 文件](https://www.tradingview.com/pine-script-docs/concepts/time/)
- 但 `_FA_STEP` 對恰為 15:00 的 close 特判為「當日」，與規格「>=15:00 屬次交易日」衝突；常態首根夜盤收在 15:04/15:05 時不觸發，仍應修正或正式定義例外。
- 週末／休市時，Pine `close[1]` 與引擎 `_ST["last"]` 一致：例如週一日盤會引用上週五夜盤末（約 05:00），不是上週五 13:45。這是否符合「前一交易日收盤」必須先定義並做黃金測試。
- 回測引擎強制 `limit_tp=1, trail_cap=0`，較接近 v30f，並非 v30e 的 trailing-exit 語意；因此結果不能作為 v30e 的部署驗證。
- 統計證據不足以實盤：2024+ 僅約 7–9 個觸發日、被擋 Add 本身為正期望，且約 15 個同日變體／閾值掃描、事後由實盤交易提出。placebo 結果雖有利，仍不足抵銷選擇偏誤。

必修項目：定義週末/休市參考價、移除 15:00 歧義、限制策略只能跑 5 分鐘、對 v30e/v30f 各自做逐筆 Pine–引擎對帳，並以預先固定規則做 shadow 記錄。Webhook JSON 結構未改；v30f 的 `tp_sync` 只會反映較小持倉。換版後必須重建 TradingView alert，既有 alert 不會套用新腳本快照。[官方說明](https://tradingview.com/pine-script-docs/faq/alerts/)