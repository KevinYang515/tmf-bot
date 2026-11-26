"""STAGE2 dashboard update (keeps strategy() capital/commission identical to v30e live settings)."""
from pathlib import Path
p = Path(r"E:\stock\v38_v29_snr_20261017\TF_V38_v30e_stage2.pine")
raw = p.read_bytes().decode("utf-8"); crlf = "\r\n" in raw; s = raw.replace("\r\n", "\n")
def rep(o, n):
    global s; assert s.count(o) == 1, (s.count(o), o[:60]); s = s.replace(o, n)
# strategy(): same capital / commission / slippage as live v30e
assert 'initial_capital=400000' in s and 'commission_value=380, slippage=0' in s
rep('var table board = table.new(position.top_right, 2, 17,', 'var table board = table.new(position.top_right, 2, 19,')
rep('"V38 v30e (v30d+停用多單G)"', '"V38 STAGE2 (v30e+LB7S/LL5/S24/NS5/SAT1/BDL1)"')
rep('''        else if posSize == -3 and useGuerrilla
            addStr := str.tostring(nextAddPrice, "#") + " (游擊) ⚔️"
        else
            addStr := "全軍出擊 (Max 4)"
''', '''        else if posSize == -3 and useGuerrilla
            addStr := str.tostring(nextAddPrice, "#") + " (游擊) ⚔️"
        else
            addStr := "全軍出擊 (Max 4)"
        if posSize > -4 and not shortAddOk2
            addStr := "⛔ 暫停加空 (" + (not shortLateAddOk ? "跌≥7%" : not ns5Ok ? "夜盤跌≥5%" : "高於昨收") + ")"
''')
adx_cell = '    table.cell(board, 1, 15, adxStr, text_color=not useAdx ? color.gray : isAdxOk ? color.green : color.red)\n'
rep(adx_cell, adx_cell + '''
    // ★ STAGE2：首單過濾 / 距昨收 / BDL1 狀態
    float _pcChg = na(lbPrevClose) ? na : (close / lbPrevClose - 1) * 100
    float _from7Low = na(low7d) ? na : (close / low7d - 1) * 100
    float _from24H = na(high24h) ? na : (1 - close / high24h) * 100
    string fltStr = (longLateOk ? "多:可開" : "多:⛔追高 " + str.tostring(_from7Low, "0.0") + "%") + " | " + (shortMomOk ? "空:可開" : "空:⛔未跌夠 " + str.tostring(_from24H, "0.0") + "%")
    table.cell(board, 0, 16, "LL5 / S24 首單過濾", text_color=color.white)
    table.cell(board, 1, 16, fltStr, text_color=(longLateOk and shortMomOk) ? color.green : color.orange)
    float _dhChg = (na(lbPrevClose) or na(bdlDayHigh)) ? na : (bdlDayHigh / lbPrevClose - 1) * 100
    string bdlStr = "距昨收 " + str.tostring(_pcChg, "0.00") + "% | BDL1 " + (not useBDL1 ? "未啟用" : bdlHit ? "今日已觸發" : "日高 " + str.tostring(_dhChg, "0.0") + "% (≥5%後回落1%觸發)")
    table.cell(board, 0, 17, "距昨收 / BDL1", text_color=color.white)
    table.cell(board, 1, 17, bdlStr, text_color=bdlHit ? color.fuchsia : color.gray)
    string capStr = "本金 400,000 | 手續費 380/口 | 滑價 0（同 v30e）"
    table.cell(board, 0, 18, "回測設定", text_color=color.white)
    table.cell(board, 1, 18, capStr, text_color=color.gray)
''')
if crlf: s = s.replace("\n", "\r\n")
p.write_bytes(s.encode("utf-8")); print("dashboard updated")
