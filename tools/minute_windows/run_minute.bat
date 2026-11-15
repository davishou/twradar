@echo off
rem Minute K data: run by Windows Task Scheduler at 14:40 daily
rem Data, keys and log live in D:\twradar-minute (not in the repo)
set MINUTE_DIR=D:\twradar-minute\data
set MINUTE_ENV=D:\twradar-minute\minute.env
set PYTHONUTF8=1
cd /d "%~dp0..\.."
set TASK=%1
if "%TASK%"=="" set TASK=auto
echo ===== %date% %time% %TASK% >> D:\twradar-minute\log.txt
py -3.12 -m pipeline.minute %TASK% 300 >> D:\twradar-minute\log.txt 2>&1
