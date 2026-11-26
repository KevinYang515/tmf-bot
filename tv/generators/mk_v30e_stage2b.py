"""STAGE2b = STAGE2 + dashboard size/position/compact/hide inputs (trading logic untouched). Originals untouched."""
import re
from pathlib import Path
H = Path(r"E:\stock\v38_v29_snr_20261017")
raw = (H / "TF_V38_v30e_stage2.pine").read_bytes().decode("utf-8")
crlf = "\r\n" in raw
s = raw.replace("\r\n", "\n")
def rep(o, n):
    global s; assert s.count(o) == 1, (s.count(o), o[:60]); s = s.replace(o, n)

old_tbl = 'var table board = table.new(position.top_right, 2, 19, bgcolor=color.new(color.black, 20), border_width=1, border_color=color.gray)\n'
rep(old_tbl, '''grp_dash = "📋 儀表板顯示"
dashShow = input.bool(true, "顯示儀表板", group=grp_dash)
dashMode = input.string("精簡", "顯示模式", options=["精簡", "完整"], group=grp_dash, tooltip="精簡：只留損益/回撤/交易數/保本/持倉/加碼目標/首單過濾")
dashSizeStr = input.string("小", "字體大小", options=["極小", "小", "一般"], group=grp_dash)
dashPosStr = input.string("右下", "位置", options=["右上", "右下", "左上", "左下", "中下"], group=grp_dash)
dashSize = dashSizeStr == "極小" ? size.tiny : dashSizeStr == "小" ? size.small : size.normal
dashPos = dashPosStr == "右上" ? position.top_right : dashPosStr == "右下" ? position.bottom_right : dashPosStr == "左上" ? position.top_left : dashPosStr == "左下" ? position.bottom_left : position.bottom_center
var table board = table.new(dashPos, 2, 19, bgcolor=color.new(color.black, 20), border_width=1, border_color=color.gray)
''')
# font size on every cell
lines = s.split("\n"); n = 0
for i, l in enumerate(lines):
    if l.lstrip().startswith("table.cell(board,"):
        assert l.rstrip().endswith(")"), l
        lines[i] = l.rstrip()[:-1] + ", text_size=dashSize)"; n += 1
s = "\n".join(lines)
assert n == 38, n
# ROI denominator aligned with 1,000,000 capital
rep("float mtd_roi = (mtd_pnl / 400000) * 100", "float mtd_roi = (mtd_pnl / strategy.initial_capital) * 100")
rep('"V38 STAGE2 (v30e+LB7S/LL5/S24/NS5/SAT1/BDL1)"', 'dashMode == "精簡" ? "V38 STAGE2" : "V38 STAGE2 (v30e+LB7S/LL5/S24/NS5/SAT1/BDL1)"')
# compact / hide at the end of the islast block (after last cell)
last = '    table.cell(board, 1, 18, capStr, text_color=color.gray, text_size=dashSize)\n'
rep(last, last + '''    if not dashShow
        table.clear(board, 0, 0, 1, 18)
    else if dashMode == "精簡"
        table.clear(board, 0, 4, 1, 4)
        table.clear(board, 0, 7, 1, 7)
        table.clear(board, 0, 9, 1, 15)
        table.clear(board, 0, 17, 1, 18)
''')
s = "//| STAGE2b (2026-11-26): 同 STAGE2 交易邏輯，只加儀表板 大小/位置/精簡/隱藏 選項 |\n" + s
if crlf: s = s.replace("\n", "\r\n")
(H / "TF_V38_v30e_stage2b.pine").write_bytes(s.encode("utf-8")); print("wrote TF_V38_v30e_stage2b.pine, cells:", n)
