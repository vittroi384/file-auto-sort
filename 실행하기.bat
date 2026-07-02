@echo off
chcp 949 >nul
title 파일 자동 정리
cd /d "%~dp0"

python -c "import watchdog, pystray, PIL, winotify" 2>nul
if errorlevel 1 (
    echo [최초 1회] 필요한 부품을 설치합니다. 잠시만 기다려 주세요...
    python -m pip install --quiet watchdog pystray pillow winotify
)

echo 파일 자동 정리 프로그램을 시작합니다...
python auto_sort.py
if errorlevel 1 (
    echo.
    echo [문제 발생] 위 메시지를 확인해 주세요.
    pause
)
