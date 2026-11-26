"""v30e + LB7S (short-only late-add block). Original TF_V38_v30e.pine is NOT modified."""
from pathlib import Path
H = Path(r"E:\stock\v38_v29_snr_20261017")
BLOCK = '''
// ★ LB7S (2026-11-25, V067): 空單追太晚不加碼 — 價格已比「前一交易日收盤」下跌 ≥ 門檻% 時，不再新增空單 Add / G
//   （多單不受影響；空單母單與既有部位不受影響；不會平倉）
grp_lb = "★ LB7S 空單追太晚不加碼"
useLateAddBlock = input.bool(true, "啟用：比前一交易日收盤跌≥門檻%不再加空單(Add/G)", group=grp_lb)
lateAddPct = input.float(7.0, "門檻 (%)", group=grp_lb, minval=0.1, step=0.5)
// 交易日歸屬與 Python 引擎相同：K棒收盤時間 >= 15:00 (Asia/Taipei) 屬於下一個交易日
int _lbCloseH = hour(time_close, "Asia/Taipei")
int _lbDayKey = int(math.floor((time_close + 8 * 3600000 + (_lbCloseH >= 15 ? 86400000 : 0)) / 86400000))
var float lbPrevClose = na
if _lbDayKey != _lbDayKey[1]
    lbPrevClose := close[1]
bool shortLateAddOk = not useLateAddBlock or na(lbPrevClose) or ((1 - close / lbPrevClose) * 100 < lateAddPct)
'''
ANCHOR = "float avgPrice = strategy.position_avg_price\n"
EDITS = [
    ('strategy("V38.1106_v30e Session"', 'strategy("V38.1125_v30e_LB7S Session"'),
    ("    if (posSize < 0 and posSize > -3 and shortPyramidCapOk", "    if (posSize < 0 and posSize > -3 and shortLateAddOk and shortPyramidCapOk"),
    ("    if (posSize == -3 and useGuerrilla and shortPyramidCapOk", "    if (posSize == -3 and shortLateAddOk and useGuerrilla and shortPyramidCapOk"),
]
raw = (H / "TF_V38_v30e.pine").read_bytes().decode("utf-8")
crlf = "\r\n" in raw
s = raw.replace("\r\n", "\n")
for o, n in [(ANCHOR, ANCHOR + BLOCK)] + EDITS:
    assert s.count(o) == 1, o[:50]
    s = s.replace(o, n)
s = "//| LB7S (2026-11-25): + 空單追太晚不加碼 (比前一交易日收盤跌≥7% 不再加空單 Add/G) |\n" + s
if crlf: s = s.replace("\n", "\r\n")
(H / "TF_V38_v30e_lb7s.pine").write_bytes(s.encode("utf-8"))
print("wrote TF_V38_v30e_lb7s.pine")
