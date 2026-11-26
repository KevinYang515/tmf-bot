"""Append MXF 1min bars (2026-08-15 -> today) onto the corrected 20260823 dataset."""
import ast, sys
from datetime import date
from pathlib import Path
import pandas as pd
import shioaji as sj

SRC = Path(r"E:/stock/v38_v29_snr_20261017/mxf_1min_2020_20261106.csv")
CRED = Path(r"E:\D_backup\stock\minute_kbar_fetch\fetch_minute_kbars_parallel.py")
OUT = Path(__file__).with_name("mxf_1min_2020_20261110.csv")
FETCH_START = "2026-11-05"

def creds():
    vals = {}
    for n in ast.parse(CRED.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
           and n.targets[0].id in {"SJ_API_KEY", "SJ_SECRET_KEY"}:
            vals[n.targets[0].id] = ast.literal_eval(n.value)
    return vals["SJ_API_KEY"], vals["SJ_SECRET_KEY"]

existing = pd.read_csv(SRC, parse_dates=["ts"])
api = sj.Shioaji(simulation=False)
try:
    api.login(*creds())
    kb = api.kbars(api.Contracts.Futures.MXF.MXFR1, start=FETCH_START, end=date.today().isoformat())
finally:
    try: api.logout()
    except Exception: pass
f = pd.DataFrame({**kb}); f["ts"] = pd.to_datetime(f["ts"])
cols = list(existing.columns)
# overlap check: fetched vs existing on shared timestamps
ov = existing.merge(f[cols], on="ts", suffixes=("_e", "_f"))
diff = (ov[[c+"_e" for c in ["Open","High","Low","Close"]]].values != ov[[c+"_f" for c in ["Open","High","Low","Close"]]].values).any(axis=1)
print(f"overlap rows {len(ov):,}, OHLC mismatches {diff.sum()}")
new = f[f.ts > existing.ts.max()][cols]
merged = pd.concat([existing, new], ignore_index=True).sort_values("ts").reset_index(drop=True)
# spike check on new rows: 1min close-to-close move > 3% or bar range > 3%
n2 = merged[merged.ts > existing.ts.max() - pd.Timedelta(days=1)].copy()
n2["ret"] = n2.Close.pct_change().abs(); n2["rng"] = (n2.High - n2.Low) / n2.Close
print("spikes:\n", n2[(n2.ret > 0.03) | (n2.rng > 0.03)][["ts","Open","High","Low","Close","Volume"]])
days = pd.Series(merged.ts[merged.ts >= FETCH_START].dt.normalize().unique()).sort_values()
gaps = [(a.date(), b.date()) for a, b in zip(days[:-1], days[1:]) if (b - a).days > 4]
print("gaps>4d:", gaps)
merged.to_csv(OUT, index=False)
print(f"existing {existing.ts.max()} | new rows {len(new):,} -> {merged.ts.max()} | saved {OUT}")
