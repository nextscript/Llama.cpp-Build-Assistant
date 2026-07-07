@echo off
REM Llama.cpp Build Assistant - Windows launcher
REM Uses python_manager.py to pick a compatible interpreter automatically.
setlocal enableextensions
cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"

set /p VERSION=<"%SCRIPT_DIR%VERSION"

echo ========================================
echo  Llama.cpp Build Assistant (v%VERSION%)
echo ========================================
echo.

REM Auto-request admin rights (needed for winget/choco dependency installs)
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting Administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b
)

REM Find ANY python to bootstrap the interpreter selection (pure-stdlib module).
set "PYEXE="
where py >nul 2>&1 && set "PYEXE=py"
if not defined PYEXE where python >nul 2>&1 && set "PYEXE=python"
if not defined PYEXE where python3 >nul 2>&1 && set "PYEXE=python3"

if not defined PYEXE (
    echo ERROR: No Python found on this system.
    echo Please install Python 3.9+ from https://www.python.org/downloads/
    echo ^(The launcher will then auto-select a compatible version.^)
    pause
    exit /b 1
)

echo Bootstrap: selecting a compatible Python interpreter...
"%PYEXE%" "%SCRIPT_DIR%python_manager.py" bootstrap
if errorlevel 1 (
    echo ERROR: Could not obtain a compatible Python interpreter.
    echo Run: "%PYEXE%" "%SCRIPT_DIR%python_manager.py" check
    pause
    exit /b 1
)

REM Read the chosen interpreter path written by python_manager.
set "CHOSEN_PY="
if exist "%SCRIPT_DIR%.python-interpreter" (
    set /p CHOSEN_PY=<"%SCRIPT_DIR%.python-interpreter"
)
if not defined CHOSEN_PY set "CHOSEN_PY=%PYEXE%"

echo Using interpreter: %CHOSEN_PY%
echo.
echo Starting Build Assistant...
"%CHOSEN_PY%" "%SCRIPT_DIR%app.py"

if errorlevel 1 (
    echo.
    echo Application closed with an error.
    pause
) else (
    echo.
    echo Application closed.
    pause
)
