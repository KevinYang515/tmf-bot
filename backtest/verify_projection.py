def _hms_to_sec(hms):
    h, m, s = (int(x) for x in hms.split(":"))
    return h*3600+m*60+s

def project_trial(trials, snap_times, decide_time, open_time):
    if len(trials) < 2 or trials[-1] is None or trials[-2] is None:
        return trials[-1] if trials else None
    dt_last = _hms_to_sec(snap_times[-1]) - _hms_to_sec(snap_times[-2])
    dt_to_open = _hms_to_sec(open_time) - _hms_to_sec(decide_time)
    if dt_last <= 0:
        return trials[-1]
    slope = (trials[-1] - trials[-2]) / dt_last
    return trials[-1] + slope * dt_to_open

snap8 = ["08:44:30","08:44:40","08:44:45","08:44:50"]
snap15 = ["14:59:30","14:59:40","14:59:45","14:59:50"]

rows8 = [
    ("07-03", 45704, [45738,45734,45734,45700], 45695, 0.5),
    ("07-06(stale)", 47106, [47300,47300,47300,47300], 47297, 0.5),
    ("07-07", 47355, [47188,47187,47160,47138], 47062, 0.5),
    ("07-08", 45231, [45405,45412,45426,45454], 45500, 0.5),
]
rows15 = [
    ("07-03", 46993, [47099,47098,47098,47098], 47045, 0.3),
    ("07-06", 46881, [46924,46925,46925,46925], 46960, 0.3),
    ("07-07", 45763, [45851,45880,45897,45899], 45920, 0.3),
    ("07-08", 45565, [45501,45500,45500,45500], 45500, 0.3),
]

print("=== 0845 ===")
for name, ref, trials, actual, th in rows8:
    proj = project_trial(trials, snap8, "08:44:50", "08:45:00")
    raw_gap = (trials[-1]-ref)/ref*100
    proj_gap = (proj-ref)/ref*100
    actual_gap = (actual-ref)/ref*100
    raw_trig = "TRIGGER" if abs(raw_gap)>=th else "skip"
    proj_trig = "TRIGGER" if abs(proj_gap)>=th else "skip"
    flag = "  <-- 判斷改變!" if raw_trig!=proj_trig else ""
    print(f"{name}: raw={raw_gap:+.3f}%({raw_trig}) proj={proj_gap:+.3f}%({proj_trig}) actual={actual_gap:+.3f}%{flag}")

print("\n=== 1500 ===")
for name, ref, trials, actual, th in rows15:
    proj = project_trial(trials, snap15, "14:59:50", "15:00:00")
    raw_gap = (trials[-1]-ref)/ref*100
    proj_gap = (proj-ref)/ref*100
    actual_gap = (actual-ref)/ref*100
    raw_trig = "TRIGGER" if abs(raw_gap)>=th else "skip"
    proj_trig = "TRIGGER" if abs(proj_gap)>=th else "skip"
    flag = "  <-- 判斷改變!" if raw_trig!=proj_trig else ""
    print(f"{name}: raw={raw_gap:+.3f}%({raw_trig}) proj={proj_gap:+.3f}%({proj_trig}) actual={actual_gap:+.3f}%{flag}")
