s=open("gap_strategy.py",encoding="utf-8").read()
o1='''        for back in range(0, 5):
            d = (today_dt - pd.Timedelta(days=back)).strftime("%Y-%m-%d")
            rec = captures.get(f"{d}_{label}")
            if rec is not None:
                return float(rec["price"]), d
        logger.warning(f"[RefClose] 即時捕捉({label}) 4 天內無記錄 → fallback 用 kbars() 查詢")'''
n1='''        # 2026-11-23 修正：只接受『今天』的即時捕捉。舊版往回找 4 天，今天捕捉失敗時會拿到
        # 前幾天的舊價（11/19、11/20 都用了 11/18 的 39781），被誤判成跨天舊聞而整場不下單，
        # 而且根本不會走到 kbars fallback。05:00/13:45 的捕捉一定記在當天日期，所以只看今天。
        d = today_dt.strftime("%Y-%m-%d")
        rec = captures.get(f"{d}_{label}")
        if rec is not None:
            return float(rec["price"]), d
        logger.warning(f"[RefClose] 今天沒有即時捕捉({label}) → fallback 用 kbars() 查詢")'''
o2='''        bar_ts = m.iloc[-1]["ts"]
        return float(m.iloc[-1]["Close"]), bar_ts.strftime("%Y-%m-%d")'''
n2='''        bar_ts = m.iloc[-1]["ts"]
        # 2026-11-23 新增：正常是 0 天（當天）或 >=2 天（跨週末/連假，呼叫端只記錄不下單）。
        # 剛好 1 天代表 kbars 索引延遲、抓到昨天的收盤 → 參考價錯誤，回傳 None 讓本場跳過。
        lag = (pd.Timestamp(today) - bar_ts.normalize()).days
        if lag == 1:
            logger.error(f"[RefClose] kbars 只抓到昨天的 {hm[0]:02d}:{hm[1]:02d} bar（{bar_ts}）→ 參考價不可信，本場跳過")
            return None, None
        logger.info(f"[RefClose] kbars fallback 取得 {bar_ts} close={float(m.iloc[-1]['Close']):.0f}")
        return float(m.iloc[-1]["Close"]), bar_ts.strftime("%Y-%m-%d")'''
for o,n in ((o1,n1),(o2,n2)):
    assert s.count(o)==1, o[:40]; s=s.replace(o,n)
open("gap_strategy.py","w",encoding="utf-8").write(s); print("patched")
