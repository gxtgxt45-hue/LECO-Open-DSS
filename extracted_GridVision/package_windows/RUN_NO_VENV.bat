@echo off
title GridVision OpenDSS (no venv)
cd /d "%~dp0"
where py >nul 2>&1 && set PY=py || set PY=python
echo Installing packages with system Python...
%PY% -m pip install fastapi "uvicorn[standard]" python-multipart pandas openpyxl
echo Starting server...
start "" "http://127.0.0.1:8000/"
%PY% -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
