s = open("../round12/fa_run12.py", encoding="utf-8").read()
def rep(o, n):
    global s; c = s.count(o); assert c == 1, (c, o[:50]); s = s.replace(o, n)
rep('TAGS = {"S24_2"', 'TAGS = {**{f"SW_{a}_{b}_{c}_{d}": dict(N, nobe=True, ll=5.0, lb=7.0, lbsd=True, s24=2.0, pp={"s_slMult": a/10, "s_trailMult": b/10, "s_pyramid_dist": c/10, "addLossS": d/10}) '
    'for a in (20, 25, 30) for b in (25, 30, 35) for c in (8, 10, 12) for d in (40, 45, 50)}, "S24_2"')
rep('/ "round12" /', '/ "round13" /')
open("fa_run13.py", "w", encoding="utf-8").write(s); print("ok")
