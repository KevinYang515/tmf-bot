Task (work only inside E:\stock; do NOT touch the network; do NOT push):
Create a NEW local git repository at E:\stock\v38_research_repo that will hold ONLY source code and small text files from these folders (copy, do not move originals):
  - E:\stock\v38_v29_snr_20261017\gap\fable_audit\ (round4..round14 subfolders: *.py, PREREG.md, ana*.txt, *.md; NOT eng/ or eng*/ folders, NOT *.csv/*.pkl/*.log/*.json)
  - E:\stock\v38_v29_snr_20261017\*.py and *.pine (top level only), E:\stock\v38_v29_snr_20261017\gap\fable_audit\fa_cost.py
  - E:\stock\v38_v29_snr_20261017\shadow_gates\*.py
  - E:\stock\tmf_bot_ops\ (all subfolders: *.py, *.md, result*.txt, small *.csv under 200KB like attr_side.csv; skip anything larger)
  - E:\stock\research_registry\ (trials.csv and *.md)
Keep the same relative folder structure under the repo (e.g. repo\v38_v29_snr_20261017\gap\fable_audit\round12\...).
Add a .gitignore excluding *.pkl, *.log, eng*/, *.parquet, large data csv (mxf_1min*.csv), .env, __pycache__.
Secret scan BEFORE committing: grep all copied files for patterns: eyJ[A-Za-z0-9_-]{10,}, SJ_API_KEY *= *['"][^'"]+, SJ_SECRET_KEY *= *['"][^'"]+, person_id, [A-Z][12][0-9]{8}, password, token *= *['"]. Any file that contains a real secret/ID value must be EXCLUDED (list them). Files that only reference a credentials FILE PATH are fine.
Then: git init, set local user.name "Chung-Kai.Yang" (already global, just verify), git add, commit with message "V38 research code snapshot 2026-11-26 (rounds 4-14, tmf_bot_ops, registry)".
Finally print: total files, total size, list of excluded files (with reason), and `git log --stat | head -50`.
