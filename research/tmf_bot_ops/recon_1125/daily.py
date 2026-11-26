import pandas as pd
D="E:/stock/tmf_bot_ops/recon_1125/"
B=pd.read_csv(D+"balance.csv",encoding="utf-8-sig",parse_dates=["datetime"])
print(B[B.datetime<"2026-11-13"][["datetime","session","yesterday_balance","today_balance","future_open_position"]].to_string())
F=pd.read_csv(D+"fills.csv",parse_dates=["ts"])
print(F[F.ts<"2026-11-12 06:00"][["ts","qty","px","comment","pos"]].to_string())
E=pd.read_csv("E:/stock/v38_v29_snr_20261017/shadow_gates/v30eopt_off0_base_latest.csv",parse_dates=["entry_ts","exit_ts"])
E["d"]=(E.exit_ts+pd.Timedelta(hours=10,minutes=15)).dt.normalize()   # 13:46 cut: exits after 13:45 count to next day
B["d"]=B.datetime.dt.normalize(); day=B[B.session=="日盤"].set_index("d").today_balance
x=pd.DataFrame({"實盤":day.diff(),"引擎off0":E.groupby("d").pnl.sum()}).loc["2026-11-12":"2026-11-25"].fillna(0)/1e4
x["差"]=x["實盤"]-x["引擎off0"]; print(x.round(1).to_string()); print("合計",x.sum().round(1).to_dict())
