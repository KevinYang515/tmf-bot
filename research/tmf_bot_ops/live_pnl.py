"""Read-only: live account realized P&L since strategy restart + open positions.
Run ONLY outside trading hours (05:00-08:45 or 13:45-15:00). Never places orders. Prints no account ids."""
import ast, sys, json
from datetime import date
from pathlib import Path
import pandas as pd

CRED = Path(r"E:\D_backup\stock\minute_kbar_fetch\fetch_minute_kbars_parallel.py")
START = sys.argv[1] if len(sys.argv) > 1 else "2026-11-11"
OUT = Path(r"E:\stock\tmf_bot_ops\data")


def creds():
    v = {}
    for n in ast.parse(CRED.read_text(encoding="utf-8")).body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
           and n.targets[0].id in {"SJ_API_KEY", "SJ_SECRET_KEY"}:
            v[n.targets[0].id] = ast.literal_eval(n.value)
    return v["SJ_API_KEY"], v["SJ_SECRET_KEY"]


import shioaji as sj
api = sj.Shioaji(simulation=False)
try:
    api.login(*creds())
    acc = api.futopt_account
    pl = api.list_profit_loss(acc, begin_date=START, end_date=date.today().isoformat())
    rows = []
    for p in pl:
        d = {k: getattr(p, k, None) for k in ("date", "code", "direction", "quantity", "entry_price", "cover_price", "pnl", "fee", "tax")}
        d["direction"] = str(d["direction"])
        rows.append(d)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / f"live_pnl_{START}_{date.today()}.csv", index=False, encoding="utf-8-sig")
    pos = [{"code": p.code, "direction": str(p.direction), "quantity": p.quantity, "price": p.price,
            "last_price": p.last_price, "pnl": p.pnl} for p in api.list_positions(acc)]
    try:
        m = api.margin(acc)
        margin = {k: getattr(m, k, None) for k in ("equity", "equity_amount", "available_margin", "initial_margin",
                                                   "maintenance_margin", "today_balance", "yesterday_balance", "risk_indicator")}
    except Exception as e:
        margin = {"error": type(e).__name__}
finally:
    try:
        api.logout()
    except Exception:
        pass

pd.set_option("display.width", 200)
print(df.to_string(index=False) if len(df) else "no realized rows")
if len(df):
    for c in ("pnl", "fee", "tax"):
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    g = df.groupby("date")[["quantity", "pnl", "fee", "tax"]].sum(); g["net"] = g.pnl - g.fee - g.tax
    print(g.to_string()); print("TOTAL pnl", df.pnl.sum(), "fee", df.fee.sum(), "tax", df.tax.sum(), "net", (df.pnl - df.fee - df.tax).sum())
print("POSITIONS", json.dumps(pos, ensure_ascii=False, default=str))
print("MARGIN", json.dumps(margin, ensure_ascii=False, default=str))
