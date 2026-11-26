"""V38 v30e 錨點閘門影子紀錄（只記錄，不下單、不碰 VM）。
每天跑一次：
  1. 用永豐 kbars（唯讀）把 MXF 1 分 K 補到最新 -> mxf_1min_live.csv
  2. 跑 v30e（off0、市價出場 = 目前實盤的 TV 版本）
  3. 對 SHADOW_START 之後的每個波段，判斷三個閘門會不會擋：
       T1     : 空單母單進場時，訊號 K 收盤 > 前一交易日收盤
       T1p05  : 任何空單進場時，訊號 K 收盤 > 前一交易日收盤 x 1.005
       V1S    : 空單母單進場時，訊號 K 收盤 > 當盤 VWAP
       SO     : 空單母單進場時，訊號 K 收盤 > 當盤開盤價（Fable round3 B3，2026-11-12 加入）
       A1_15  : 試單停損後同向母單需價格先走 1.5 ATR（當日），兩條引擎路徑比較（2026-11-12 加入）
       LMA20  : 前一交易日收盤 < 20 日均線時不做多單母單（round4 L_MA20，2026-11-17 加入）
     母單被擋 -> 整個波段（flat-to-flat）算被擋；T1p05 另外記被擋的加碼/游擊單口
  4. 輸出 shadow_blocks.csv（每次全部重算，可重複跑）與 shadow_summary.csv、shadow.log
放棄規則（round2 PREREG）：某版本被擋的波段累積 >= 40 個且合計淨損益 >= 0 -> 放棄該版本。
淨損益用成本 R（手續費 + ATR 縮放滑價，開盤 K 50 點），與研究一致。
近似：離線判斷，不重跑「擋掉之後」的路徑（擋掉母單後可能稍後另開一單，這裡不模擬）。"""
import os, sys, ast, inspect, argparse
from datetime import date, datetime
from pathlib import Path
import numpy as np, pandas as pd

HERE = Path(r"E:\stock\v38_v29_snr_20261017"); SD = HERE / "shadow_gates"
SEED = HERE / "mxf_1min_2020_20261111c.csv"; LIVE = SD / "mxf_1min_live.csv"
SHADOW_START = pd.Timestamp(os.environ.get("SHADOW_START", "2026-11-12 00:00"))
CRED = Path(r"E:\D_backup\stock\minute_kbar_fetch\fetch_minute_kbars_parallel.py")
LOG = SD / "shadow.log"


def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------- 1. data refresh ----------
def creds():
    vals = {}
    for n in ast.parse(CRED.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
           and n.targets[0].id in {"SJ_API_KEY", "SJ_SECRET_KEY"}:
            vals[n.targets[0].id] = ast.literal_eval(n.value)
    return vals["SJ_API_KEY"], vals["SJ_SECRET_KEY"]


def refresh():
    import shioaji as sj
    src = LIVE if LIVE.exists() else SEED
    ex = pd.read_csv(src, parse_dates=["ts"]); last = ex.ts.max()
    start = (last - pd.Timedelta(days=1)).date().isoformat()
    api = sj.Shioaji(simulation=False)
    try:
        api.login(*creds())
        kb = api.kbars(api.Contracts.Futures.MXF.MXFR1, start=start, end=date.today().isoformat())
    finally:
        try:
            api.logout()
        except Exception:
            pass
    f = pd.DataFrame({**kb}); f["ts"] = pd.to_datetime(f["ts"]); cols = list(ex.columns)
    px = ["Open", "High", "Low", "Close"]
    ov = ex.merge(f[cols], on="ts", suffixes=("_e", "_f"))
    mis = int((ov[[c + "_e" for c in px]].values != ov[[c + "_f" for c in px]].values).any(axis=1).sum())
    # 重疊區以新抓的為準（盤中跑會留下未完成的最後一根，下次要覆蓋掉）
    new = f[f.ts > last][cols]; fresh = f[cols]
    m = pd.concat([ex[ex.ts < fresh.ts.min()], fresh], ignore_index=True).sort_values("ts").reset_index(drop=True)
    tmp = LIVE.with_suffix(".tmp"); m.to_csv(tmp, index=False); os.replace(tmp, LIVE)
    log(f"data: {src.name} last {last} | overlap {len(ov)} mismatches {mis} | +{len(new)} rows -> {m.ts.max()}")


# ---------- 2. engine (same construction as gap/latest1111c/run.py, v30e opt off0) ----------
def run_engine():
    os.environ["GAP_BASE"] = "engine_g2lb_wrapper"; sys.path.insert(0, str(HERE))
    import importlib.util
    import engine_gap_wrapper as gw
    # Fable round3 的記憶體內引擎修補（A1/B3/T1 開關；全關時與原引擎逐筆相同，見 round3/cmp_impl.py）
    spec = importlib.util.spec_from_file_location("fa3", HERE / "gap" / "fable_audit" / "round3" / "fa_run3_fable.py")
    fa3 = importlib.util.module_from_spec(spec); spec.loader.exec_module(fa3)
    G = gw._g; G["_TF"], G["_OFF"] = 5, 0; base = gw._lb

    def build_bars(df1m, minutes):
        if minutes != 60:
            t = df1m["open_ts"]; off = pd.Timedelta(minutes=G["_OFF"])
            g = df1m.groupby((t - off).dt.floor("5min") + off)
            bars = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                                 "close": g["close"].last(), "close_ts": g["ts"].max()})
            bars.index.name = "open_ts"; return bars.reset_index()
        return base._base.build_bars(df1m, 60)
    G["build_bars"] = build_bars
    exec(compile(inspect.getsource(base._base.prepare), "prepare_off", "exec"), G)
    gsrc = inspect.getsource(base._g2_vf).replace('    if lb == 20:\n        return volume_features(df1, b5)\n', '')
    gsrc = gsrc.replace('minute["bin"] = minute["open_ts"].dt.floor("5min")',
                        'minute["bin"] = (minute["open_ts"] - pd.Timedelta(minutes=_OFF)).dt.floor("5min") + pd.Timedelta(minutes=_OFF)')
    assert "_OFF" in gsrc; exec(compile(gsrc, "g2vf_off", "exec"), G)
    V30 = {**gw.P, "opt_stale_hr": 10, "opt_cooldown_min": 30, "opt_short_pyramid_cap_mode": "hour4",
           "l_trailBase": 3.5, "l_trailBaseDay": 3.5, "l_trailBaseNight": 3.5, "adxThresh": 30}
    p = {**V30, "opt_ml_gate": {"variant": "G2", "session_cum_vol_rel20_threshold": 0.7277710401830155, "lookback": 20,
                                "fix_all_next_minute": True, "no_long_g": True}}
    df = gw.load_1min(LIVE); out = {}
    for tag, cfg in [("base", {}), ("A1_15", {"a1": 1.5})]:
        fa3._FA_CFG.update(fa3.N); fa3._FA_CFG.update(cfg)
        fa3._ST.update(d=None, prev=None, last=None, sopen=None, lastclose_ts=None)
        fa3._FA_S.update(lock={1: None, -1: None}, early=False, n_blk=0, n_early=0, n_lock=0)
        t = gw.run(df, p=p, intrabar_mode="1min")
        t.to_csv(SD / f"v30eopt_off0_{tag}_latest.csv", index=False); out[tag] = t
    return out


# ---------- 3. cost R + gates ----------
def cost_R(T, m):
    b = m.resample("5min", label="left", closed="right").agg({"High": "max", "Low": "min", "Close": "last"}).dropna()
    tr = pd.concat([b.High - b.Low, (b.High - b.Close.shift()).abs(), (b.Low - b.Close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False).mean(); ref = atr["2026-05-19":"2026-09-23"].median()

    def slip(ts, kind):
        a = atr.reindex(ts, method="ffill").to_numpy()
        s = 3 * np.clip(a / ref, 0.67, 3) * np.where(kind.isin(["Add", "G"]), 1.3, 1.0)
        hm = ts.dt.strftime("%H:%M")
        return np.where(hm.between("08:40", "08:45") | hm.between("14:55", "15:00"), 50, s)
    fee = lambda px: 20 + 0.00002 * px * 50
    return T.pnl - fee(T.entry_px) - fee(T.exit_px) - (slip(T.entry_ts, T.kind) + slip(T.exit_ts, T.kind)) * 50


def gates(T, m):
    c = m.Close
    # 前一交易日收盤（同 round1/2 引擎 _FA_STEP：交易日 = 日期，15:00 後算下一日）
    dkey = c.index.normalize() + pd.to_timedelta((c.index.hour >= 15).astype(int), "D")
    dclose = c.groupby(dkey).last(); prevc = dclose.shift(1)
    ma20 = dclose.rolling(20).mean().shift(1)   # 前一交易日為止的 20 日均線（round4 L_MA20）
    # 當盤 VWAP（間隔 > 30 分視為新盤，典型價加權，同 round2 r2c_vwap_offline.py）
    idx = m.index; sid = np.r_[0, np.cumsum((idx[1:] - idx[:-1]) > pd.Timedelta(minutes=30))]
    tp = (m.High + m.Low + m.Close) / 3
    vw = (tp * m.Volume).groupby(sid).cumsum() / m.Volume.groupby(sid).cumsum()
    # entry_ts 是成交那一分鐘；同標籤的 1 分 K = 訊號 K 最後一分鐘（round2 慣例）
    T["sig_close"] = c.reindex(T.entry_ts).values
    ek = T.entry_ts.dt.normalize() + pd.to_timedelta((T.entry_ts.dt.hour >= 15).astype(int), "D")
    T["prev_close"] = prevc.reindex(ek).values; T["vwap"] = vw.reindex(T.entry_ts).values
    sh = T.side == "S"; cmd = T.kind == "Cmd"
    T["g_T1"] = sh & cmd & (T.sig_close > T.prev_close)
    T["g_T1p05"] = sh & (T.sig_close > T.prev_close * 1.005)
    T["g_V1S"] = sh & cmd & (T.sig_close > T.vwap)
    # B3（Fable round3）：空單母單進場時，訊號 K 收盤 > 當盤開盤價（盤 = 間隔 > 30 分後第一根）
    T["sess_open"] = m.Open.groupby(sid).transform("first").reindex(T.entry_ts).values
    T["g_SO"] = sh & cmd & (T.sig_close > T.sess_open)
    # L_MA20（round4, 2026-11-17 加入）：前一交易日收盤 < 20 日均線時不做多單母單
    T["ma20"] = ma20.reindex(ek).values
    T["g_LMA20"] = (T.side == "L") & cmd & (T.prev_close < T.ma20)
    return T


def campaigns(T):
    T = T.sort_values("entry_ts").reset_index(drop=True); cid = []; cur = 0; end = pd.Timestamp("1900-01-01")
    for en, ex in zip(T.entry_ts, T.exit_ts):
        if en >= end:
            cur += 1
        end = max(end, ex); cid.append(cur)
    T["cid"] = cid
    return T


def analyse(R):
    m = pd.read_csv(LIVE, parse_dates=["ts"]).set_index("ts").sort_index()
    T = R["base"].copy(); T["entry_ts"] = pd.to_datetime(T.entry_ts); T["exit_ts"] = pd.to_datetime(T.exit_ts)
    T["net_R"] = cost_R(T, m); T = gates(campaigns(T), m)
    T.to_pickle(SD / "trades_gated.pkl")
    T = T[T.entry_ts >= SHADOW_START]
    rows = []
    for g in ["T1", "T1p05", "V1S", "SO", "LMA20"]:
        for cid, c in T.groupby("cid"):
            first = c.sort_values("entry_ts").iloc[0]
            if first.kind == "Cmd" and first[f"g_{g}"]:
                rows.append(dict(gate=g, scope="campaign", cid=cid, entry_ts=first.entry_ts, side=first.side, lots=len(c),
                                 sig_close=first.sig_close, prev_close=first.prev_close, vwap=round(first.vwap, 1),
                                 exit_ts=c.exit_ts.max(), net_R=round(c.net_R.sum()), open=bool((c.exit_sig == "END").any())))
            elif g == "T1p05":
                for _, r in c[c.g_T1p05 & (c.kind != "Cmd")].iterrows():
                    rows.append(dict(gate=g, scope="lot", cid=cid, entry_ts=r.entry_ts, side=r.side, lots=1,
                                     sig_close=r.sig_close, prev_close=r.prev_close, vwap=round(r.vwap, 1),
                                     exit_ts=r.exit_ts, net_R=round(r.net_R), open=r.exit_sig == "END"))
    cols = ["gate", "scope", "cid", "entry_ts", "side", "lots", "sig_close", "prev_close", "vwap", "exit_ts", "net_R", "open"]
    B = pd.DataFrame(rows, columns=cols)
    B.to_csv(SD / "shadow_blocks.csv", index=False, encoding="utf-8-sig")
    S = []
    for g in ["T1", "T1p05", "V1S", "SO", "LMA20"]:
        b = B[(B.gate == g) & ~B.open.astype(bool)]; nc = int((b.scope == "campaign").sum()); tot = int(b.net_R.sum())
        if nc >= 40:
            verdict = "放棄（被擋的合計不虧）" if tot >= 0 else "可考慮上線（滿40且被擋合計為虧）"
        else:
            verdict = "觀察中"
        S.append(dict(gate=g, blocked_campaigns=nc, blocked_lots_extra=int((b.scope == "lot").sum()), blocked_net_R=tot, verdict=verdict))
    # A1_15（Fable round3）：試單（只有母單、沒加碼）停損出場後，同向母單要等價格朝該方向走 >= 1.5 ATR（當日有效）
    # 跟路徑有關，所以直接跑兩條引擎路徑比較：被擋 = base 有、A1 沒有的母單；效果 = 兩條路徑的成本 R 淨損益差
    A = R["A1_15"].copy(); A["entry_ts"] = pd.to_datetime(A.entry_ts); A["exit_ts"] = pd.to_datetime(A.exit_ts); A["net_R"] = cost_R(A, m)
    A = A[A.entry_ts >= SHADOW_START]
    key = lambda x: set(zip(x.entry_ts, x.side))
    bc = T[T.kind == "Cmd"]; blk = bc[[k not in key(A[A.kind == "Cmd"]) for k in zip(bc.entry_ts, bc.side)]]
    for _, r in blk.iterrows():
        c = T[T.cid == r.cid]
        rows.append(dict(gate="A1_15", scope="campaign", cid=r.cid, entry_ts=r.entry_ts, side=r.side, lots=len(c), sig_close=r.sig_close,
                         prev_close=r.prev_close, vwap=round(r.vwap, 1), exit_ts=c.exit_ts.max(), net_R=round(c.net_R.sum()),
                         open=bool((c.exit_sig == "END").any())))
    B = pd.DataFrame(rows, columns=cols); B.to_csv(SD / "shadow_blocks.csv", index=False, encoding="utf-8-sig")
    da = int(A[A.exit_sig != "END"].net_R.sum() - T[T.exit_sig != "END"].net_R.sum())
    nb = int((~B[B.gate == "A1_15"].open.astype(bool)).sum())
    S.append(dict(gate="A1_15", blocked_campaigns=nb, blocked_lots_extra=0, blocked_net_R=-da,
                  verdict=("放棄（路徑差 <= 0）" if da <= 0 else "可考慮上線（滿40且路徑差 > 0）") if nb >= 40 else "觀察中"))
    S = pd.DataFrame(S); S.to_csv(SD / "shadow_summary.csv", index=False, encoding="utf-8-sig")
    base = T[T.exit_sig != "END"]
    log(f"since {SHADOW_START.date()}: v30e off0 closed lots {len(base)}, campaigns {base.cid.nunique()}, net_R {int(base.net_R.sum()):+,d}")
    for _, r in S.iterrows():
        log(f"  {r.gate:6s} blocked campaigns {r.blocked_campaigns:3d} (+{r.blocked_lots_extra} lots)  blocked net_R {r.blocked_net_R:+,d}  -> {r.verdict}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--no-fetch", action="store_true"); a = ap.parse_args()
    try:
        if not a.no_fetch:
            refresh()
        elif not LIVE.exists():
            import shutil; shutil.copy(SEED, LIVE)
        analyse(run_engine())
    except Exception as e:
        log(f"ERROR {type(e).__name__}: {e}")
        raise
