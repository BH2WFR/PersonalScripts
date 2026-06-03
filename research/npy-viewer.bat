@echo off
REM ============================================
REM  npy/npz file viewer launcher
REM  Usage: double-click a .npy/.npz file, or
REM        drag-and-drop a file onto this script
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
set "FILE_PATH=%~1"

if "%FILE_PATH%"=="" (
    "%PYTHON%" "%SCRIPT_DIR%npy-viewer.py"
) else (
    "%PYTHON%" "%SCRIPT_DIR%npy-viewer.py" "%FILE_PATH%"
)

if ERRORLEVEL 1 (
    echo.
    echo Script exited with error code: %ERRORLEVEL%
    pause
)
