@echo off
setlocal enabledelayedexpansion
title ZeroPort - Windows build

rem ---------------------------------------------------------------------------
rem  Builds dist\ZeroPort.exe from a clean virtual environment.
rem
rem    build_windows.bat            venv, deps, icon, tests, package
rem    build_windows.bat --no-tests skip the test run
rem ---------------------------------------------------------------------------

cd /d "%~dp0"

set "SKIP_TESTS="
if /i "%~1"=="--no-tests" set "SKIP_TESTS=1"

set "VENV=.venv"
set "PY=%VENV%\Scripts\python.exe"

echo.
echo   ZeroPort build
echo   --------------
echo.

rem --- 1. Python ------------------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo   [X] Python was not found on PATH.
    echo       Install Python 3.11 or newer from python.org and try again.
    goto :failed
)

rem --- 2. Virtual environment ----------------------------------------------
if not exist "%PY%" (
    echo   [1/5] Creating virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 goto :failed
) else (
    echo   [1/5] Using existing virtual environment.
)

rem --- 3. Dependencies ------------------------------------------------------
echo   [2/5] Installing dependencies...
"%PY%" -m pip install --upgrade pip --quiet
if errorlevel 1 goto :failed
"%PY%" -m pip install -r requirements-dev.txt --quiet
if errorlevel 1 goto :failed

rem --- 4. Icon --------------------------------------------------------------
if not exist "assets\icon.ico" (
    echo   [3/5] Generating application icon...
    "%PY%" tools\make_icon.py
    if errorlevel 1 goto :failed
) else (
    echo   [3/5] Icon already present.
)

rem --- 5. Tests -------------------------------------------------------------
if defined SKIP_TESTS (
    echo   [4/5] Skipping tests ^(--no-tests^).
) else (
    echo   [4/5] Running tests...
    "%PY%" -m pytest -q
    if errorlevel 1 (
        echo.
        echo   [X] Tests failed. The executable was not built.
        goto :failed
    )
)

rem --- 6. Package -----------------------------------------------------------
echo   [5/5] Packaging with PyInstaller...
if exist "build" rmdir /s /q "build"
if exist "dist\ZeroPort.exe" del /q "dist\ZeroPort.exe"
"%PY%" -m PyInstaller ZeroPort.spec --noconfirm --clean --log-level WARN
if errorlevel 1 goto :failed

if not exist "dist\ZeroPort.exe" (
    echo   [X] PyInstaller finished but dist\ZeroPort.exe is missing.
    goto :failed
)

for %%F in ("dist\ZeroPort.exe") do set "EXE_SIZE=%%~zF"
set /a EXE_MB=!EXE_SIZE! / 1048576

echo.
echo   [OK] Build succeeded.
echo        dist\ZeroPort.exe  (!EXE_MB! MB)
echo.
echo        Right-click the file to create a desktop shortcut.
echo.
endlocal
exit /b 0

:failed
echo.
echo   [X] Build failed.
echo.
endlocal
exit /b 1
