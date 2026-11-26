"""Make LB7 (late add block) Pine variants from v30e / v30f. Originals are NOT modified."""
from pathlib import Path
H = Path(r"E:\stock\v38_v29_snr_20261017")
BLOCK = '''
// ★ LB7 (2026-11-25, V063): 追太晚不加碼 — 價格已比「前一交易日收盤」順向走 ≥ 門檻% 時，不再新增 Add / G（母單與既有部位不受影響）
grp_lb = "★ LB7 追太晚不加碼"
useLateAddBlock = input.bool(true, "啟用：比前一交易日收盤順向走≥門檻%不再加碼/G", group=grp_lb)
lateAddPct = input.float(7.0, "門檻 (%)", group=grp_lb, minval=0.1, step=0.5)
// 交易日歸屬與 Python 引擎相同：K棒收盤時間 >= 15:00 (Asia/Taipei) 屬於下一個交易日
int _lbCloseH = hour(time_close, "Asia/Taipei")
int _lbDayKey = int(math.floor((time_close + 8 * 3600000 + (_lbCloseH >= 15 ? 86400000 : 0)) / 86400000))
var float lbPrevClose = na
if _lbDayKey != _lbDayKey[1]
    lbPrevClose := close[1]
bool lateAddOk = not useLateAddBlock or na(lbPrevClose) or posSize == 0 or ((close / lbPrevClose - 1) * 100 * (posSize > 0 ? 1 : -1) < lateAddPct)
'''
ANCHOR = "float avgPrice = strategy.position_avg_price\n"
EDITS = [
    ("    if (posSize > 0 and posSize < 3 and not isLongToxic", "    if (posSize > 0 and posSize < 3 and lateAddOk and not isLongToxic"),
    ("    if (posSize == 3 and useGuerrilla and useGuerrillaLong and", "    if (posSize == 3 and lateAddOk and useGuerrilla and useGuerrillaLong and"),
    ("    if (posSize < 0 and posSize > -3 and shortPyramidCapOk", "    if (posSize < 0 and posSize > -3 and lateAddOk and shortPyramidCapOk"),
    ("    if (posSize == -3 and useGuerrilla and shortPyramidCapOk", "    if (posSize == -3 and lateAddOk and useGuerrilla and shortPyramidCapOk"),
]
for src, dst, old_t, new_t in [("TF_V38_v30e.pine", "TF_V38_v30e_lb7.pine", 'strategy("V38.1106_v30e Session"', 'strategy("V38.1125_v30e_LB7 Session"'),
                               ("TF_V38_v30f.pine", "TF_V38_v30f_lb7.pine", 'strategy("V38.1111_v30f LimitTP"', 'strategy("V38.1125_v30f_LB7 LimitTP"')]:
    raw = (H / src).read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    s = raw.replace("\r\n", "\n")
    for o, n in [(ANCHOR, ANCHOR + BLOCK), (old_t, new_t)] + EDITS:
        assert s.count(o) == 1, (src, o[:50])
        s = s.replace(o, n)
    s = "//| LB7 (2026-11-25): + 追太晚不加碼 (比前一交易日收盤順向≥7% 不再 Add/G) |\n" + s
    if crlf: s = s.replace("\n", "\r\n")
    (H / dst).write_bytes(s.encode("utf-8"))
    print("wrote", dst)
