exec(open("run.py",encoding="utf-8").read().split("rows=[]")[0])
for D,R,h in ((6,3,240),(10,4,240)):
    ev=[]
    for k in range(10,len(days)):
        s,e=np.searchsorted(di,k),np.searchsorted(di,k+1)
        hi10=dh[k-10:k].max(); low_prev=dl[k-2:k].min()
        runlow=np.minimum.accumulate(L[s:e]); low3=np.minimum(runlow,low_prev)
        cond=(low3<=hi10*(1-D/100))&(C[s:e]>=low3*(1+R/100))
        if cond.any(): ev.append(s+np.argmax(cond))
    r=pd.Series([(C[p+h]-C[p]-COST)/C[p]*1e4 for p in ev if p+h<len(C)],index=[idx[p] for p in ev if p+h<len(C)])
    g=r.groupby(r.index.to_period("Q")).agg(['size','sum','mean']).round(0)
    print(f"\nD={D} R={R} h={h} 依季：", g[g['size']>0].to_string())
    print("2026-11:", r["2026-11"].round(0).to_dict())
