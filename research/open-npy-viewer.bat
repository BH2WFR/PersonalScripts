@echo off
REM ============================================
REM  npy/npz 文件查看器启动脚本
REM  用法：双击 .npy/.npz 文件自动打开，或
REM       拖放文件到此脚本上
REM ============================================

REM 设置控制台代码页为 UTF-8，避免中文乱码
chcp 65001 >nul

REM 加载 conda 环境（需确保已执行过 conda init cmd.exe）
call conda activate base

set "SCRIPT_DIR=%~dp0"
set "SHOW_SCRIPT=%SCRIPT_DIR%show_npy.py"

REM 获取传入的文件路径（支持拖放和双击关联）
set "FILE_PATH=%~1"

if "%FILE_PATH%"=="" (
    python "%SHOW_SCRIPT%"
) else (
    python "%SHOW_SCRIPT%" "%FILE_PATH%"
)

REM 如果脚本异常退出，暂停以查看错误信息
if ERRORLEVEL 1 (
    echo.
    echo 脚本异常退出，错误码：%ERRORLEVEL%
    pause
)
