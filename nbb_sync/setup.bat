@echo off
cd /d "%~dp0"
echo %~dp0 | findstr /i /c:"Temp1_" /c:".zip" >nul && goto :notextracted
echo === National Broadband sync: one-time setup ===

rem crawl4ai needs Python 3.12: newer versions such as 3.15 have no ready-made packages yet.
py -3.12 --version >nul 2>&1 && goto :havepy
echo Installing Python 3.12 next to your current Python...
py install 3.12
py -3.12 --version >nul 2>&1 && goto :havepy
echo.
echo Python 3.12 could not be installed automatically.
echo Please install Python 3.12 from the page that opens now, then run setup.bat again.
start "" https://www.python.org/downloads/release/python-31210/
pause
exit /b

:havepy
rem Remove an install made with a different Python version, such as the failed 3.15 one.
if exist .venv\Scripts\python.exe .venv\Scripts\python.exe -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)" || rmdir /s /q .venv
if not exist .venv\Scripts\python.exe py -3.12 -m venv .venv
call .venv\Scripts\activate
echo Installing crawl4ai, a few minutes the first time...
python -m pip install -q --upgrade pip
pip install -q --only-binary=fastuuid,PyYAML crawl4ai || goto :installfailed
echo Installing the browser crawl4ai uses...
crawl4ai-setup
if not exist .env copy .env.example .env >nul
echo.
echo Notepad will open .env: paste your CRON_KEY after "CRON_KEY=", save with Ctrl+S and close Notepad.
notepad .env
echo.
echo Now log in to the panel once. A browser window opens: enter your password and security answer.
python nbb_sync.py login
echo.
echo First sync:
python nbb_sync.py sync
echo.
echo Scheduling an automatic sync every hour while this PC is on...
schtasks /Create /SC HOURLY /TN "NBB Panel Sync" /TR "\"%~dp0run_sync.bat\"" /F >nul && echo Done: Task Scheduler runs it every hour.
echo.
echo Setup finished. If you ever see "Panel session expired", double-click login.bat.
pause
exit /b

:installfailed
echo.
echo Install failed. Please send a screenshot of the messages above.
pause
exit /b

:notextracted
echo Please extract the zip first: right-click it, Extract All, then run setup.bat from the new folder.
pause
exit /b
