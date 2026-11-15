@echo off
rem 分鐘 K 本機排程用（Windows 工作排程器每天 14:40 執行這個檔）
rem 資料、金鑰、紀錄都放在 D:\twradar-minute，不在 repo 裡
set MINUTE_DIR=D:\twradar-minute\data
set MINUTE_ENV=D:\twradar-minute\minute.env
set PYTHONUTF8=1
cd /d "%~dp0..\.."
set TASK=%1
if "%TASK%"=="" set TASK=auto
echo ===== %date% %time% %TASK% >> D:\twradar-minute\log.txt
py -3.12 -m pipeline.minute %TASK% 300 >> D:\twradar-minute\log.txt 2>&1
