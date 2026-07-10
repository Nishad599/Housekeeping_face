@echo off
title Git Push
cd /d %~dp0
echo ========================================
echo   Quick Git Push
echo ========================================
echo.

set /p msg="Commit message: "

if "%msg%"=="" (
    echo ERROR: Commit message cannot be empty.
    pause
    exit /b 1
)

git add .
git commit -m "%msg%"
git push origin main

echo.
echo ========================================
echo   Pushed successfully!
echo ========================================
pause
