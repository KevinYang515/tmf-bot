"""v30e + LB7S (short late-add block) + LL5 (late long-Cmd block). Original TF_V38_v30e.pine is NOT modified."""
from pathlib import Path
H = Path(r"E:\stock\v38_v29_snr_20261017")
BLOCK = '''
// ★ LB7S (2026-11-25, V067): 空單追太晚不加碼 — 價格已比「前一交易日收盤」下跌 ≥ 門檻% 時，不再新增空單 Add / G
// ★ LL5  (2026-11-25, V071): 多單追太高不開母單 — 價格已比「近7天(日曆)最低價」高 ≥ 門檻% 時，不開新多單 Cmd
//   （兩者都只擋新單；既有部位、出場、停損不受影響；不會平倉）
grp_lb = "★ LB7S / LL5 追太晚過濾"
useLateAddBlock = input.bool(true, "啟用 LB7S：比前一交易日收盤跌≥門檻%不再加空單(Add/G)", group=grp_lb)
lateAddPct = input.float(7.0, "  LB7S 門檻 (%)", group=grp_lb, minval=0.1, step=0.5)
useLongLate = input.bool(true, "啟用 LL5：比近7天最低價漲≥門檻%不開多單母單", group=grp_lb)
longLatePct = input.float(5.0, "  LL5 門檻 (%)", group=grp_lb, minval=0.1, step=0.5)
// 交易日歸屬與 Python 引擎相同：K棒收盤時間 >= 15:00 (Asia/Taipei) 屬於下一個交易日
int _lbCloseH = hour(time_close, "Asia/Taipei")
int _lbDayKey = int(math.floor((time_close + 8 * 3600000 + (_lbCloseH >= 15 ? 86400000 : 0)) / 86400000))
var float lbPrevClose = na
if _lbDayKey != _lbDayKey[1]
    lbPrevClose := close[1]
bool shortLateAddOk = not useLateAddBlock or na(lbPrevClose) or ((1 - close / lbPrevClose) * 100 < lateAddPct)
// 近7天(日曆、以K棒收盤時間計)最低價：單調佇列，與 Python 引擎 _FA_LLSTEP 相同（含本根 low）
var float[] _llQ = array.new_float()
var int[] _llT = array.new_int()
while array.size(_llQ) > 0 and array.get(_llQ, array.size(_llQ) - 1) >= low
    array.pop(_llQ)
    array.pop(_llT)
array.push(_llQ, low)
array.push(_llT, time_close)
int _llLim = time_close - 7 * 86400000
while array.size(_llT) > 0 and array.get(_llT, 0) < _llLim
    array.shift(_llQ)
    array.shift(_llT)
float low7d = array.size(_llQ) > 0 ? array.get(_llQ, 0) : na
bool longLateOk = not useLongLate or na(low7d) or close < low7d * (1 + longLatePct / 100)
// ★ S24 (2026-11-25, V073): 空單母單需「近24小時最高價」已下跌 ≥ 門檻% 才開（行情還沒動起來不先空）
useShortMom = input.bool(true, "啟用 S24：空單母單需比近24小時最高價跌≥門檻%", group=grp_lb)
shortMomPct = input.float(2.0, "  S24 門檻 (%)", group=grp_lb, minval=0.1, step=0.5)
var float[] _hQ = array.new_float()
var int[] _hT = array.new_int()
while array.size(_hQ) > 0 and array.get(_hQ, array.size(_hQ) - 1) <= high
    array.pop(_hQ)
    array.pop(_hT)
array.push(_hQ, high)
array.push(_hT, time_close)
int _hLim = time_close - 24 * 3600000
while array.size(_hT) > 0 and array.get(_hT, 0) < _hLim
    array.shift(_hQ)
    array.shift(_hT)
float high24h = array.size(_hQ) > 0 ? array.get(_hQ, 0) : na
bool shortMomOk = not useShortMom or na(high24h) or ((1 - close / high24h) * 100 >= shortMomPct)
'''
ANCHOR = "float avgPrice = strategy.position_avg_price\n"
EDITS = [
    ('strategy("V38.1106_v30e Session"', 'strategy("V38.1125_v30e_LB7S_LL5_S24 Session"'),
    ("    if (posSize == 0 and not isLongToxic and finalMtfBull and close > emaLocalLong and longTrigger",
     "    if (posSize == 0 and longLateOk and not isLongToxic and finalMtfBull and close > emaLocalLong and longTrigger"),
    ("    if (posSize == 0 and not isShortToxic and finalMtfBear and close < emaLocalShort and shortTrigger",
     "    if (posSize == 0 and shortMomOk and not isShortToxic and finalMtfBear and close < emaLocalShort and shortTrigger"),
    ("    if (posSize < 0 and posSize > -3 and shortPyramidCapOk", "    if (posSize < 0 and posSize > -3 and shortLateAddOk and shortPyramidCapOk"),
    ("    if (posSize == -3 and useGuerrilla and shortPyramidCapOk", "    if (posSize == -3 and shortLateAddOk and useGuerrilla and shortPyramidCapOk"),
]
raw = (H / "TF_V38_v30e.pine").read_bytes().decode("utf-8")
crlf = "\r\n" in raw
s = raw.replace("\r\n", "\n")
for o, n in [(ANCHOR, ANCHOR + BLOCK)] + EDITS:
    assert s.count(o) == 1, o[:60]
    s = s.replace(o, n)
s = "//| LB7S+LL5 (2026-11-25): 空單比昨收跌≥7%不加碼；多單比7日低點漲≥5%不開母單；空單母單需比24h高點跌≥2% |\n" + s
if crlf: s = s.replace("\n", "\r\n")
(H / "TF_V38_v30e_lb7s_ll5_s24.pine").write_bytes(s.encode("utf-8"))
print("wrote TF_V38_v30e_lb7s_ll5_s24.pine")
