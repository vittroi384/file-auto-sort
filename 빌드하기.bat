@echo off
chcp 949 >nul
title EXE 만들기 (공유용)
cd /d "%~dp0"

echo ============================================================
echo  파이썬 없이 쓸 수 있는 EXE 파일을 만듭니다.
echo  (이 작업은 파이썬이 깔린 내 PC에서 한 번만 하면 됩니다)
echo ============================================================
echo.
echo [1/2] 필요한 도구를 설치합니다...
python -m pip install --quiet --upgrade pyinstaller watchdog pystray pillow winotify
if errorlevel 1 (
    echo [실패] 설치 중 문제가 발생했습니다. 파이썬 설치 여부를 확인하세요.
    pause
    exit /b 1
)

echo.
echo [2/2] EXE 파일을 만드는 중입니다. 1~3분 걸릴 수 있어요...
python -m PyInstaller --onefile --name "파일자동정리" --clean --noconfirm auto_sort.py

if not exist "dist\파일자동정리.exe" (
    echo.
    echo [실패] EXE 생성에 실패했습니다. 위 메시지를 확인해 주세요.
    pause
    exit /b 1
)

if exist "배포용" rmdir /S /Q "배포용"
mkdir "배포용"
copy /Y "dist\파일자동정리.exe" "배포용\파일자동정리.exe" >nul
copy /Y "rules.txt" "배포용\rules.txt" >nul
if exist "폴더목록.txt" copy /Y "폴더목록.txt" "배포용\폴더목록.txt" >nul
if exist "보낼곳목록.txt" copy /Y "보낼곳목록.txt" "배포용\보낼곳목록.txt" >nul
if exist "받는분_읽어주세요.txt" copy /Y "받는분_읽어주세요.txt" "배포용\받는분_읽어주세요.txt" >nul

echo.
echo ============================================================
echo  [완료]  배포용 폴더가 만들어졌습니다.
echo    - 파일자동정리.exe
echo    - rules.txt / 폴더목록.txt / 보낼곳목록.txt
echo    - 받는분_읽어주세요.txt
echo.
echo  이 배포용 폴더를 통째로 ZIP으로 압축해서 보내세요.
echo ============================================================
explorer "배포용"
pause
