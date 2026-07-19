@echo off
REM ================================================================
REM   HomeUpdater - Initial Setup Script (TEST MODE)
REM   ASCII-only. Auto-elevates. Logs to logs\setup_<timestamp>.log
REM ================================================================

setlocal enabledelayedexpansion
title HomeUpdater - Setup
color 0B

REM ----------------------------------------------------------------
REM Resolve project root and prepare logs directory
REM ----------------------------------------------------------------
set "PROJECT_ROOT=%~dp0"
set "LOG_DIR=%PROJECT_ROOT%logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" 2>nul

REM Get a locale-safe timestamp via PowerShell (YYYYMMDD_HHMMSS)
for /f "delims=" %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%i"
set "LOG_FILE=%LOG_DIR%\setup_%TS%.log"
set "LATEST_LOG=%LOG_DIR%\setup_latest.log"

REM ----------------------------------------------------------------
REM Auto-elevate to Administrator
REM ----------------------------------------------------------------
net session >nul 2>&1
if %errorLevel% NEQ 0 (
    echo.
    echo ================================================================
    echo                  HomeUpdater - Setup [TEST MODE]
    echo ================================================================
    echo.
    echo [!] Requesting Administrator privileges...
    echo     A UAC prompt will appear - click Yes
    echo.
    timeout /t 2 /nobreak > nul
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

echo.
echo ================================================================
echo                  HomeUpdater - Project Setup
echo                       [TEST MODE]
echo ================================================================
echo.
echo [OK] Running as Administrator
echo [i]  Log file: %LOG_FILE%
echo.

REM Check PowerShell availability
where powershell >nul 2>&1
if %errorLevel% NEQ 0 (
    echo [X] PowerShell not found. This is unusual on Windows 10/11.
    pause
    exit /b 1
)

echo [-] Launching PowerShell setup script...
echo.
echo ================================================================
echo.

REM Run the actual PowerShell setup script (it handles its own transcript)
powershell -ExecutionPolicy Bypass -NoProfile -File "%PROJECT_ROOT%setup.ps1" -LogFile "%LOG_FILE%"
set PS_EXIT=%errorlevel%

REM Copy this run's log to setup_latest.log for easy reference
if exist "%LOG_FILE%" copy /Y "%LOG_FILE%" "%LATEST_LOG%" >nul 2>&1

echo.
echo ================================================================
if %PS_EXIT% EQU 0 (
    color 0A
    echo.
    echo                 [OK] Setup completed successfully
    echo.
    echo   Next: double-click run.bat to start the project.
    echo   Log saved to: %LOG_FILE%
) else (
    color 0C
    echo.
    echo                 [X]  Setup failed - exit code %PS_EXIT%
    echo.
    echo   Review the log file for error details:
    echo   %LOG_FILE%
)
echo ================================================================
echo.
pause
exit /b %PS_EXIT%
