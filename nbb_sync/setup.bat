@echo off
cd /d "%~dp0"
echo %~dp0 | findstr /i /c:"Temp1_" /c:".zip" >nul && (echo Please extract the zip first: right-click it, Extract All, then run setup.bat from the new folder. & pause & exit /b)
echo === National Broadband sync: one-time setup ===
where py >nul 2>&1 || (echo Python is not installed. Install Python 3.11 from python.org and tick "Add Python to PATH", then run setup.bat again. & start "" https://www.python.org/downloads/ & pause & exit /b)
if not exist .venv ( py -m venv .venv )
call .venv\Scripts\activate
echo Installing crawl4ai (a few minutes the first time)...
python -m pip install -q --upgrade pip
pip install -q crawl4ai || (echo Install failed. Check your internet connection and run setup.bat again. & pause & exit /b)
echo Installing the browser crawl4ai uses...
crawl4ai-setup
if not exist .env copy .env.example .env >nul
echo.
echo Notepad will open .env: paste your CRON_KEY after "CRON_KEY=", save (Ctrl+S) and close Notepad.
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
