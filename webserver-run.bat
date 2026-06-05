@echo off
REM ============================================
REM  Static web server launcher
REM  Usage: double-click to start interactive,
REM        or run with --dir/--bind/--port flags
REM ============================================

chcp 65001 >nul

REM Find python: prefer conda, fall back to PATH
set "PYTHON="
for %%p in (
    "%USERPROFILE%\miniconda3\python.exe"
    "%USERPROFILE%\anaconda3\python.exe"
    "%ProgramData%\miniconda3\python.exe"
    "%ProgramData%\anaconda3\python.exe"
) do (
    if exist %%p if "%PYTHON%"=="" set "PYTHON=%%p"
)
if "%PYTHON%"=="" set "PYTHON=python"

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

"%PYTHON%" "%SCRIPT_DIR%webserver-run.py" %*
if ERRORLEVEL 1 pause
