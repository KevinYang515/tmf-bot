import pandas as pd, numpy as np
m=pd.read_csv('E:/stock/v38_v29_snr_20261017/shadow_gates/mxf_1min_live.csv',parse_dates=['ts']).set_index('ts')
td=(m.index+pd.to_timedelta(np.where(m.index.hour>=15,9,0),unit='h')).normalize()
d=m.groupby(td).agg(O=('Open','first'),H=('High','max'),L=('Low','min'),C=('Close','last'))
d['rngp']=(d.H-d.L)/d.C*100; d['rngpt']=d.H-d.L; d['absret']=d.C.pct_change().abs()*100
q=d.groupby(d.index.to_period('Q')).agg(px=('C','mean'),rng_pct=('rngp','median'),rng_pts=('rngpt','median'),absret=('absret','mean'))
print(q.round(2).to_string())
r=d.rngp.rolling(20).median(); print('\n20日振幅中位數 歷史百分位: 目前', round(r.iloc[-1],2), '分位', round((r<=r.iloc[-1]).mean()*100,1))
for lab,a,b in [('2020/3 疫情','2020-03-01','2020-04-15'),('2022 升息空頭','2022-01-01','2022-10-31'),('2024/8 日圓套利','2024-08-01','2024-08-20'),('2025/4 關稅','2025-04-01','2025-04-30'),('2026/10/29~11/17','2026-10-29','2026-11-17')]:
    z=d[a:b]; print(f'{lab:16s} 日振幅中位 {z.rngp.median():.2f}% ({z.rngpt.median():.0f}點) 最大 {z.rngp.max():.1f}% 高低 {z.C.max():.0f}->{z.C.min():.0f} 天數{len(z)}')
