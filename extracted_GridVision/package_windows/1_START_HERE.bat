@echo off
title GridVision OpenDSS
color 0A
cd /d "%~dp0"

echo.
echo =====================================================
echo   GridVision + OpenDSS
echo =====================================================
echo Folder: %CD%
echo.

if not exist "%~dp0app.py" (
  echo ERROR: app.py missing. Extract the full zip first.
  pause
  exit /b 1
)
if not exist "%~dp0GridVision_OpenDSS_app.html" (
  echo ERROR: GridVision_OpenDSS_app.html missing.
  pause
  exit /b 1
)

REM ---- Find Python ----
set PY=
where py >nul 2>&1
if %ERRORLEVEL%==0 (
  set PY=py
) else (
  where python >nul 2>&1
  if %ERRORLEVEL%==0 (
    set PY=python
  ) else (
    echo ERROR: Python not found.
    echo Install from https://www.python.org/downloads/
    echo IMPORTANT: check "Add python.exe to PATH"
    pause
    exit /b 1
  )
)
echo Python launcher: %PY%
%PY% --version
echo.

REM ---- Remove broken venv (no pip) ----
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m pip --version >nul 2>&1
  if errorlevel 1 (
    echo [FIX] Existing .venv has no pip — deleting and recreating...
    rmdir /s /q "%~dp0.venv" 2>nul
  )
)

REM ---- Create venv ----
if not exist "%~dp0.venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv "%~dp0.venv"
  if errorlevel 1 (
    echo ERROR: could not create venv
    pause
    exit /b 1
  )
)

set VPY=%~dp0.venv\Scripts\python.exe
set VPIP=%~dp0.venv\Scripts\pip.exe

REM ---- Ensure pip inside venv ----
echo Ensuring pip...
"%VPY%" -m ensurepip --upgrade >nul 2>&1
"%VPY%" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo [FIX] Bootstrapping pip with get-pip...
  "%VPY%" -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '_get_pip.py')"
  if exist "%~dp0_get_pip.py" (
    "%VPY%" "%~dp0_get_pip.py"
    del "%~dp0_get_pip.py" 2>nul
  )
)

"%VPY%" -m pip --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo ERROR: pip still missing in venv.
  echo Try this manually in Command Prompt:
  echo   cd /d "%~dp0"
  echo   rmdir /s /q .venv
  echo   %PY% -m venv .venv
  echo   .venv\Scripts\python.exe -m ensurepip --upgrade
  echo   .venv\Scripts\python.exe -m pip install fastapi "uvicorn[standard]" python-multipart pandas openpyxl
  echo.
  echo Or install packages with system Python and run without venv:
  echo   %PY% -m pip install fastapi "uvicorn[standard]" python-multipart pandas openpyxl
  echo   %PY% -m uvicorn app:app --host 127.0.0.1 --port 8000
  pause
  exit /b 1
)

echo Installing / updating packages...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install fastapi "uvicorn[standard]" python-multipart pandas openpyxl
if errorlevel 1 (
  echo.
  echo WARNING: venv pip install failed — trying system Python pip...
  %PY% -m pip install fastapi "uvicorn[standard]" python-multipart pandas openpyxl
  if errorlevel 1 (
    echo ERROR: package install failed. Check internet connection.
    pause
    exit /b 1
  )
  echo Starting with system Python...
  echo.
  echo =====================================================
  echo   SERVER  http://127.0.0.1:8000/
  echo   KEEP THIS WINDOW OPEN
  echo =====================================================
  echo.
  start "" "http://127.0.0.1:8000/?v=heatmap1"
  %PY% -m uvicorn app:app --host 127.0.0.1 --port 8000
  echo Server stopped.
  pause
  exit /b 0
)

echo.
echo =====================================================
echo   SERVER  http://127.0.0.1:8000/
echo   Map + Results + Methodology + time slider + Scan heat map
echo   KEEP THIS WINDOW OPEN
echo =====================================================
echo.

start "" "http://127.0.0.1:8000/?v=heatmap1"
"%VPY%" -m uvicorn app:app --host 127.0.0.1 --port 8000

echo Server stopped.
pause
