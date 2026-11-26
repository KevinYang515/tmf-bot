import pandas as pd, numpy as np
def us_open_tpe(ts):
    d=ts.normalize()
    if ts.hour<12: d=d-pd.Timedelta(days=1)   # 凌晨屬前一天美股盤
    ny=pd.Timestamp(d.date()).tz_localize("America/New_York")+pd.Timedelta(hours=9,minutes=30)
    return ny.tz_convert("Asia/Taipei").tz_localize(None)
def lab(ts):
    mm=ts.hour*60+ts.minute
    if 525<=mm<540: return "台日盤開盤15分"
    if 540<=mm<555: return "台日盤開盤15-30分"
    if 900<=mm<915: return "台夜盤開盤15分"
    if 915<=mm<930: return "台夜盤開盤15-30分"
    uo=us_open_tpe(ts); dm=(ts-uo).total_seconds()/60
    if 0<=dm<15: return "美股開盤15分"
    if 15<=dm<30: return "美股開盤15-30分"
    if -60<=dm<0: return "美股開盤前1小時"
    return "其他"
pd.set_option("display.width",220)
for nm,f in (("現行","camp2.pkl"),("新版","camp3.pkl")):
    K=pd.read_pickle(f); K["窗"]=K.start.map(lab); K["期"]=np.where(K.start<"2024","20-23","24+"); K["side"]=K.side.map({"L":"多","S":"空"})
    t=K.groupby(["窗","side","期"]).agg(n=("net","size"),勝率=("net",lambda s:round((s>0).mean()*100)),平均萬=("net",lambda s:round(s.mean()/1e4,2)),合計萬=("net",lambda s:round(s.sum()/1e4,1))).unstack("期")
    print(f"\n===== {nm} ====="); print(t.to_string())
