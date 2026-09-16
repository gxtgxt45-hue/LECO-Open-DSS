GridVision OpenDSS — BZ0109 complete package
============================================
1) Unzip this folder anywhere (path without special characters preferred).
2) Double-click 1_START_HERE.bat
3) Wait until browser opens http://127.0.0.1:8000/
4) Hard refresh once: Ctrl+Shift+R

Included data
- LOAD_PROFILE_10_09_2026.xlsx  (15 days: 2026-08-11 to 2026-08-25) — active study days
- BZ0109LP.xlsx                  (earlier June–July LP kept as backup)
- DATA BZ0109.xls                (monthly consumption + ACCOUNT→POLE)
- SOLAR REPORT on Poles (1).xlsx
- BZ0109.zip                     (network KMZ/GIS)
- account_pole_map.json          (leading zeros stripped on numeric accounts)

Upload any new LP + DATA later: choose files → Upload → Process.
All operations (map, time slider, heat map, full results, pole V compare) use the processed LP days.

Python: 3.10+ recommended. Packages: fastapi uvicorn pandas openpyxl xlrd python-multipart
If venv fails, use RUN_NO_VENV.bat after: pip install -r requirements.txt
