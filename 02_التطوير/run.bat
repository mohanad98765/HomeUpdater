@echo off
REM ================================================================
REM   HomeUpdater - Run Script (TEST MODE)
REM   ASCII-only. Auto-elevates. Logs to logs\<kind>_<timestamp>.log
REM   Delegates backend/frontend launching to PowerShell helper scripts
REM   under scripts\ to avoid nested-quote issues with Arabic paths.
REM ================================================================

setlocal enabledelayedexpansion
title HomeUpdater - Launcher

set "PROJECT_ROOT=%~dp0"
set "LOG_DIR=%PROJECT_ROOT%logs"
set "SCRIPTS_DIR=%PROJECT_ROOT%scripts"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul

REM Locale-safe timestamp
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "RUN_LOG=%LOG_DIR%\run_%TS%.log"
set "BACKEND_LOG=%LOG_DIR%\backend_%TS%.log"
set "FRONTEND_LOG=%LOG_DIR%\frontend_%TS%.log"
set "LATEST_RUN=%LOG_DIR%\run_latest.log"
set "LATEST_BACKEND=%LOG_DIR%\backend_latest.log"
set "LATEST_FRONTEND=%LOG_DIR%\frontend_latest.log"

REM ----------------------------------------------------------------
REM Auto-elevate to Administrator
REM ----------------------------------------------------------------
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo.
    echo ================================================================
    echo                  HomeUpdater - Launcher [TEST MODE]
    echo ================================================================
    echo.
    echo [!] Requesting Administrator privileges...
    echo     A UAC prompt will appear - click Yes
    echo.
    timeout /t 2 /nobreak > nul
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

cd /d "%PROJECT_ROOT%"

REM ----------------------------------------------------------------
REM Header
REM ----------------------------------------------------------------
> "%RUN_LOG%" echo HomeUpdater launcher started
>>"%RUN_LOG%" echo Project root: %PROJECT_ROOT%
>>"%RUN_LOG%" echo Run log:      %RUN_LOG%
>>"%RUN_LOG%" echo Backend log:  %BACKEND_LOG%
>>"%RUN_LOG%" echo Frontend log: %FRONTEND_LOG%

echo.
echo ================================================
echo   HomeUpdater - Launcher
echo   [TEST MODE]
echo ================================================
echo.
echo   Run log:      %RUN_LOG%
echo   Backend log:  %BACKEND_LOG%
echo   Frontend log: %FRONTEND_LOG%
echo.

REM ----------------------------------------------------------------
REM Verify prerequisites
REM ----------------------------------------------------------------
echo [1/4] Checking prerequisites...

if not exist "backend\.venv\Scripts\python.exe" (
    echo.
    echo [X] Python virtual environment not found.
    echo     Run setup.bat first.
    >>"%RUN_LOG%" echo [X] Missing backend\.venv\Scripts\python.exe
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo.
    echo [X] Node packages not installed.
    echo     Run setup.bat first.
    >>"%RUN_LOG%" echo [X] Missing frontend\node_modules
    pause
    exit /b 1
)

if not exist "%SCRIPTS_DIR%\start_backend.ps1" (
    echo.
    echo [X] Helper script not found: scripts\start_backend.ps1
    >>"%RUN_LOG%" echo [X] Missing helper: start_backend.ps1
    pause
    exit /b 1
)

echo     [OK] Python venv ready
echo     [OK] Node packages ready
echo     [OK] Helper scripts ready
>>"%RUN_LOG%" echo [OK] All prerequisites satisfied
echo.

REM ----------------------------------------------------------------
REM Launch Backend (PowerShell helper handles Tee-Object)
REM ----------------------------------------------------------------
echo [2/4] Starting Backend (FastAPI) on port 8000...
>>"%RUN_LOG%" echo [2/4] Starting Backend
start "HomeUpdater - Backend" /D "%PROJECT_ROOT%" powershell -NoProfile -NoExit -ExecutionPolicy Bypass -File "%SCRIPTS_DIR%\start_backend.ps1" -LogFile "%BACKEND_LOG%"

timeout /t 3 /nobreak > nul

REM ----------------------------------------------------------------
REM Launch Frontend
REM ----------------------------------------------------------------
echo [3/4] Starting Frontend (Vite) on port 5173...
>>"%RUN_LOG%" echo [3/4] Starting Frontend
start "HomeUpdater - Frontend" /D "%PROJECT_ROOT%" powershell -NoProfile -NoExit -ExecutionPolicy Bypass -File "%SCRIPTS_DIR%\start_frontend.ps1" -LogFile "%FRONTEND_LOG%"

timeout /t 5 /nobreak > nul

REM ----------------------------------------------------------------
REM Open browser
REM ----------------------------------------------------------------
echo [4/4] Opening browser...
>>"%RUN_LOG%" echo [4/4] Opening http://127.0.0.1:5173
start "" "http://127.0.0.1:5173"

REM Update latest pointers
copy /Y "%RUN_LOG%" "%LATEST_RUN%" >nul 2>&1

echo.
echo ================================================
echo   [OK] Launched successfully
echo ================================================
echo.
echo   Backend:    http://127.0.0.1:8000
echo   Frontend:   http://127.0.0.1:5173
echo   API Docs:   http://127.0.0.1:8000/docs
echo.
echo   To stop: close the Backend and Frontend windows.
echo.
pause
