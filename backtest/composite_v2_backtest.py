"""
Composite v2 — 用 CLEAN feature (無 lookahead) 跑真實 PnL 回測
================================================================
進場: 08:46 TX 開盤 (集合競價估算)
出場: A 配置 — TP1 +100, TP2 +200, Stop -150, session 末平倉 13:44
PnL: 2 lots × NT$10/pt - commission

對照組:
  V0   NQ |%|>0.5  (現行)
  Vk   KOSPI_open_gap |%|>0.5
  Vk1  KOSPI_open_gap |%|>1.0  (更高品質)
  Vn   NKX_open_gap |%|>0.5
  Vkn  KOSPI+NKX 雙過同向 |%|>0.5  (★ 最有信心)
  Vvote vote>=2 (NQ/KOSPI/NKX)
  Vunion V0 OR Vkn 任一觸發
"""
import pandas as pd
import numpy as np
from pathlib import Path

BASE = Path(__file__).parent
POINT_VAL = 10
COMMISSION = 5.6
SLIPPAGE = 5
STOP_TICKS = 150
CUTOFF = (13, 44)

print("載入 ...", end=" ", flush=True)
df_min = pd.read_csv(BASE / "mxf_1min.csv")
df_min["ts"] = pd.to_datetime(df_min["ts"])
df_min["date"] = df_min["ts"].dt.date.astype(str)
df_min["time"] = df_min["ts"].dt.strftime("%H:%M")
df_min["minute_int"] = df_min["ts"].dt.hour * 60 + df_min["ts"].dt.minute

sig = pd.read_csv(BASE / "intraday_signals_v2.csv").set_index("date")
daily = pd.read_csv(BASE / "daily_open.csv")
daily_dict = {row["date"]: row for _, row in daily.iterrows()}

by_date = {}
for d, g in df_min.groupby("date"):
    g2 = g.sort_values("ts")
    by_date[d] = {
        "minute": g2["minute_int"].values,
        "hi": g2["High"].values.astype(np.float64),
        "lo": g2["Low"].values.astype(np.float64),
        "cl": g2["Close"].values.astype(np.float64),
        "open08": None,
    }
    op = g2[g2["time"] == "08:46"]
    if not op.empty:
        by_date[d]["open08"] = float(op.iloc[0]["Open"])
print(f"{len(by_date)} 日")


def get_open(d):
    bd = by_date.get(d)
    if bd is None: return None
    bo = bd["open08"]
    if d in daily_dict:
        v = daily_dict[d].get("open_0845")
        if v is not None and not pd.isna(v) and bo is not None:
            if abs(float(v) - bo) <= 200:
                return float(v)
    return bo


def build_bars(d):
    ch, cm = CUTOFF
    cutoff_min = ch * 60 + cm
    bd = by_date.get(d)
    if bd is None: return None
    mask = (bd["minute"] >= (8 * 60 + 46)) & (bd["minute"] <= cutoff_min)
    hi = bd["hi"][mask]
    if len(hi) == 0: return None
    return hi, bd["lo"][mask], bd["cl"][mask]


def sim_A(entry, bars, direction, tp1=100, tp2=200, stop=STOP_TICKS):
    hi, lo, cl = bars
    n = len(hi)
    be = entry + direction * SLIPPAGE
    tp1_p = be + direction * tp1
    tp2_p = be + direction * tp2
    stop_p = be - direction * stop
    stop_mask = (lo <= stop_p) if direction == 1 else (hi >= stop_p)
    stop_idx = stop_mask.argmax() if stop_mask.any() else n
    pnl = 0
    for tp_p in [tp1_p, tp2_p]:
        tp_mask = (hi >= tp_p) if direction == 1 else (lo <= tp_p)
        tp_idx = tp_mask.argmax() if tp_mask.any() else n
        if stop_idx < n and stop_idx <= tp_idx: fill = stop_p
        elif tp_idx < n: fill = tp_p
        else: fill = cl[-1]
        pnl += direction * (fill - be) - COMMISSION
    return pnl * POINT_VAL


def get_factors(d):
    if d not in sig.index: return None
    row = sig.loc[d]
    return {
        "nq":  row.get("nq_0845_pct", np.nan),
        "kos": row.get("kospi_open_gap_pct", np.nan),
        "nkx": row.get("nkx_open_gap_pct", np.nan),
    }


def sig_V0(f):
    if not pd.notna(f["nq"]): return 0
    return int(np.sign(f["nq"])) if abs(f["nq"]) > 0.5 else 0

def sig_Vk_05(f):
    if not pd.notna(f["kos"]): return 0
    return int(np.sign(f["kos"])) if abs(f["kos"]) > 0.5 else 0

def sig_Vk_10(f):
    if not pd.notna(f["kos"]): return 0
    return int(np.sign(f["kos"])) if abs(f["kos"]) > 1.0 else 0

def sig_Vn_05(f):
    if not pd.notna(f["nkx"]): return 0
    return int(np.sign(f["nkx"])) if abs(f["nkx"]) > 0.5 else 0

def sig_Vkn_03(f):
    if not (pd.notna(f["kos"]) and pd.notna(f["nkx"])): return 0
    if abs(f["kos"]) > 0.3 and abs(f["nkx"]) > 0.3 and np.sign(f["kos"]) == np.sign(f["nkx"]):
        return int(np.sign(f["kos"]))
    return 0

def sig_Vkn_05(f):
    if not (pd.notna(f["kos"]) and pd.notna(f["nkx"])): return 0
    if abs(f["kos"]) > 0.5 and abs(f["nkx"]) > 0.5 and np.sign(f["kos"]) == np.sign(f["nkx"]):
        return int(np.sign(f["kos"]))
    return 0

def sig_Vvote(f):
    score = 0
    if pd.notna(f["nq"]) and abs(f["nq"]) > 0.2:  score += int(np.sign(f["nq"]))
    if pd.notna(f["kos"]) and abs(f["kos"]) > 0.2: score += int(np.sign(f["kos"]))
    if pd.notna(f["nkx"]) and abs(f["nkx"]) > 0.2: score += int(np.sign(f["nkx"]))
    return int(np.sign(score)) if abs(score) >= 2 else 0

def sig_Vvote3(f):
    score = 0
    if pd.notna(f["nq"]) and abs(f["nq"]) > 0.2:  score += int(np.sign(f["nq"]))
    if pd.notna(f["kos"]) and abs(f["kos"]) > 0.2: score += int(np.sign(f["kos"]))
    if pd.notna(f["nkx"]) and abs(f["nkx"]) > 0.2: score += int(np.sign(f["nkx"]))
    return int(np.sign(score)) if abs(score) >= 3 else 0

def sig_Vunion(f):
    """V0 OR Vkn 同向 — 兩個都觸發就用 V0 方向"""
    s_nq = sig_V0(f)
    s_kn = sig_Vkn_05(f)
    if s_nq != 0 and s_kn != 0:
        return s_nq if s_nq == s_kn else s_nq  # 衝突取 NQ
    return s_nq if s_nq != 0 else s_kn


def run(sig_fn, label):
    trades = []
    for d in sig.index:
        f = get_factors(d)
        if f is None: continue
        s = sig_fn(f)
        if s == 0: continue
        bars = build_bars(d)
        if bars is None: continue
        entry = get_open(d)
        if entry is None: continue
        pnl = sim_A(entry, bars, s)
        trades.append((d, s, pnl, f))
    if not trades:
        return {"label": label, "n": 0, "trades": []}
    pnls = np.array([t[2] for t in trades])
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = (peak - cum).max()
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {
        "label": label,
        "n": len(pnls),
        "total": round(pnls.sum(), 0),
        "EV": round(pnls.mean(), 0),
        "win%": round((pnls > 0).mean() * 100, 1),
        "sharpe": round(pnls.mean() / pnls.std() * np.sqrt(252), 2) if pnls.std() > 0 else 0,
        "PF": round(pf, 2),
        "maxDD": round(dd, 0),
        "trades": trades,
    }


print()
print("=" * 110)
print("【0845 v2 backtest — CLEAN features】 cutoff=13:44 exit=A(TP+100/+200 stop=-150)")
print("=" * 110)
print(f"{'label':<35s} {'n':>5s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'Sharpe':>7s} {'PF':>6s} {'maxDD':>10s}")

RESULTS = {}
for fn, lbl in [
    (sig_V0,      "V0   |NQ|>0.5%      (現行)"),
    (sig_Vk_05,   "Vk   |KOSPI_gap|>0.5%"),
    (sig_Vk_10,   "Vk1  |KOSPI_gap|>1.0%  (嚴)"),
    (sig_Vn_05,   "Vn   |NKX_gap|>0.5%"),
    (sig_Vkn_03,  "Vkn  KOSPI+NKX 雙過 >0.3% 同向"),
    (sig_Vkn_05,  "Vkn  KOSPI+NKX 雙過 >0.5% 同向 ★"),
    (sig_Vvote,   "Vvote NQ/KOS/NKX score>=2"),
    (sig_Vvote3,  "Vvote NQ/KOS/NKX score>=3"),
    (sig_Vunion,  "Vunion V0 OR Vkn(0.5)"),
]:
    r = run(fn, lbl)
    RESULTS[lbl] = r
    if r["n"] == 0:
        print(f"{lbl:<35s} 0")
        continue
    print(f"{lbl:<35s} {r['n']:>5d} {r['total']:>+10,.0f} {r['EV']:>+8,.0f} "
          f"{r['win%']:>5.1f}% {r['sharpe']:>+7.2f} {r['PF']:>6.2f} {r['maxDD']:>+10,.0f}")

# === By year ===
print()
print("=" * 110)
print("【by year — 前 3 strats】")
print("=" * 110)
for lbl in ["V0   |NQ|>0.5%      (現行)",
            "Vk   |KOSPI_gap|>0.5%",
            "Vkn  KOSPI+NKX 雙過 >0.5% 同向 ★",
            "Vunion V0 OR Vkn(0.5)"]:
    r = RESULTS[lbl]
    if r["n"] == 0: continue
    print(f"\n>>> {lbl}")
    print(f"  {'year':<6s} {'n':>4s} {'total':>10s} {'EV':>8s} {'win%':>6s} {'PF':>6s}")
    by_yr = {}
    for d, s, pnl, f in r["trades"]:
        yr = d[:4]
        by_yr.setdefault(yr, []).append(pnl)
    for yr in sorted(by_yr.keys()):
        pnls = np.array(by_yr[yr])
        wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
        pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
        print(f"  {yr:<6s} {len(pnls):>4d} {pnls.sum():>+10,.0f} {pnls.mean():>+8,.0f} "
              f"{(pnls>0).mean()*100:>5.1f}% {pf:>6.2f}")

# === V0 漏掉 但 Vkn 抓到 ===
print()
print("=" * 110)
print("【Vkn(0.5) 抓到 而 V0 漏掉 — 06/24 style 新訊號的實戰 PnL】")
print("=" * 110)
trades = []
for d in sig.index:
    f = get_factors(d)
    if f is None: continue
    s_v0 = sig_V0(f); s_vk = sig_Vkn_05(f)
    if s_vk == 0: continue
    if s_v0 == s_vk: continue
    bars = build_bars(d)
    if bars is None: continue
    entry = get_open(d)
    if entry is None: continue
    pnl = sim_A(entry, bars, s_vk)
    trades.append((d, s_vk, pnl, f))
if trades:
    pnls = np.array([t[2] for t in trades])
    wins = pnls[pnls > 0]; losses = pnls[pnls < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    print(f"n={len(pnls)}  total={pnls.sum():+,.0f}  EV={pnls.mean():+,.0f}  "
          f"win%={(pnls>0).mean()*100:.1f}%  PF={pf:.2f}")
    print(f"\n最近 15 筆明細:")
    print(f"{'date':<12s} {'dir':>4s} {'NQ%':>7s} {'KOS%':>7s} {'NKX%':>7s} {'pnl':>10s}")
    for d, s, pnl, f in trades[-15:]:
        print(f"{d:<12s} {s:>+4d} {f['nq']:>+7.2f} {f['kos']:>+7.2f} {f['nkx']:>+7.2f} {pnl:>+10,.0f}")

# === Save ===
out_records = []
for lbl, r in RESULTS.items():
    if r["n"] == 0: continue
    out_records.append({"strategy": lbl, "n": r["n"], "total": r["total"],
                        "EV": r["EV"], "win%": r["win%"], "sharpe": r["sharpe"],
                        "PF": r["PF"], "maxDD": r["maxDD"]})
out_df = pd.DataFrame(out_records)
out_df.to_csv(BASE / "composite_v2_results.csv", index=False, encoding="utf-8-sig")
print(f"\n結果 → {BASE / 'composite_v2_results.csv'}")
