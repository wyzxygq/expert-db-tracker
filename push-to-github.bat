@echo off
chcp 65001 >nul 2>&1
title 专家库追踪 - GitHub 推送
setlocal

echo ============================================================
echo   专家库动态追踪 - 一键推送到 GitHub
echo ============================================================
echo.

set "GIT=C:\Users\pengbo\.workbuddy\binaries\PortableGit\versions\1.2.0\mingw64\bin\git.exe"
set "REPO=D:\Workbuddy\2026-08-24-18-06-00\expert-db-tracker"

echo [1/2] 检查仓库状态...
"%GIT%" -C "%REPO%" status --short
echo.

echo [2/2] 推送到 GitHub (wyzxygq/expert-db-tracker)...
echo.
echo  *** 如果弹出浏览器窗口，请在浏览器中登录 GitHub 并点击授权 ***
echo.
"%GIT%" -C "%REPO%" push -u origin main
echo.

if %ERRORLEVEL% EQU 0 (
    echo ============================================================
    echo   推送成功！
    echo ============================================================
    echo.
    echo  仓库地址: https://github.com/wyzxygq/expert-db-tracker
    echo.
    echo  接下来:
    echo  1. 打开仓库 Settings -^> Secrets and variables -^> Actions
    echo     新建 Secret:  名称 PUSHPLUS_TOKEN  值填你的PushPlus Token
    echo  2. 打开 Settings -^> Pages  选 main 分支  Save
    echo  3. 打开 Actions -^> daily-update -^> Run workflow 测试
) else (
    echo ============================================================
    echo   推送失败！
    echo ============================================================
    echo.
    echo  常见原因:
    echo  1. 仓库还没创建 - 请先打开 https://github.com/new
    echo     仓库名填 expert-db-tracker  选 Public  Create repository
    echo  2. 登录被取消 - 重新双击此脚本再试一次
    echo  3. 网络问题 - 稍后重试
)

echo.
pause
