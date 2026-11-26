s = open("fa_run9.py", encoding="utf-8").read()
o = 'TAGS = {"LB7D"'; assert s.count(o) == 1
s = s.replace(o, 'TAGS = {**{f"LB{str(x).replace(\'.\', \'p\')}": dict(N, nobe=True, lb=float(x)) for x in (4, 5.5, 6, 6.5, 7.5, 8, 9)}, "LB7D"')
open("fa_run9.py", "w", encoding="utf-8").write(s); print("ok")
