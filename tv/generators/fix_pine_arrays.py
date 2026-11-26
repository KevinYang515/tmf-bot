"""Fix Pine 'array.get index -1' (Pine evaluates both sides of `and` in while conditions).
Rewrites the two monotonic-deque loops (7-day low, 24h high) into guarded loops. Applies to the LB7S/LL5/S24/STAGE2 files."""
from pathlib import Path
H = Path(r"E:\stock\v38_v29_snr_20261017")
FIXES = [
 ("while array.size(_llQ) > 0 and array.get(_llQ, array.size(_llQ) - 1) >= low\n    array.pop(_llQ)\n    array.pop(_llT)\n",
  "_llBackDone = false\nwhile not _llBackDone\n    if array.size(_llQ) == 0\n        _llBackDone := true\n    else if array.get(_llQ, array.size(_llQ) - 1) >= low\n        array.pop(_llQ)\n        array.pop(_llT)\n    else\n        _llBackDone := true\n"),
 ("while array.size(_llT) > 0 and array.get(_llT, 0) < _llLim\n    array.shift(_llQ)\n    array.shift(_llT)\n",
  "_llFrontDone = false\nwhile not _llFrontDone\n    if array.size(_llT) == 0\n        _llFrontDone := true\n    else if array.get(_llT, 0) < _llLim\n        array.shift(_llQ)\n        array.shift(_llT)\n    else\n        _llFrontDone := true\n"),
 ("while array.size(_hQ) > 0 and array.get(_hQ, array.size(_hQ) - 1) <= high\n    array.pop(_hQ)\n    array.pop(_hT)\n",
  "_hBackDone = false\nwhile not _hBackDone\n    if array.size(_hQ) == 0\n        _hBackDone := true\n    else if array.get(_hQ, array.size(_hQ) - 1) <= high\n        array.pop(_hQ)\n        array.pop(_hT)\n    else\n        _hBackDone := true\n"),
 ("while array.size(_hT) > 0 and array.get(_hT, 0) < _hLim\n    array.shift(_hQ)\n    array.shift(_hT)\n",
  "_hFrontDone = false\nwhile not _hFrontDone\n    if array.size(_hT) == 0\n        _hFrontDone := true\n    else if array.get(_hT, 0) < _hLim\n        array.shift(_hQ)\n        array.shift(_hT)\n    else\n        _hFrontDone := true\n"),
 ("float low7d = array.size(_llQ) > 0 ? array.get(_llQ, 0) : na\n",
  "float low7d = na\nif array.size(_llQ) > 0\n    low7d := array.get(_llQ, 0)\n"),
 ("float high24h = array.size(_hQ) > 0 ? array.get(_hQ, 0) : na\n",
  "float high24h = na\nif array.size(_hQ) > 0\n    high24h := array.get(_hQ, 0)\n"),
]
for fn in ("TF_V38_v30e_lb7s_ll5.pine", "TF_V38_v30e_lb7s_ll5_s24.pine", "TF_V38_v30e_stage2.pine"):
    p = H / fn; raw = p.read_bytes().decode("utf-8"); crlf = "\r\n" in raw; s = raw.replace("\r\n", "\n"); n = 0
    for o, new in FIXES:
        if o in s: s = s.replace(o, new); n += 1
    assert "array.size(_llQ) > 0 and" not in s and "array.size(_hQ) > 0 and" not in s
    if crlf: s = s.replace("\n", "\r\n")
    p.write_bytes(s.encode("utf-8")); print(fn, "fixed blocks:", n)
