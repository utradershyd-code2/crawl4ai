@echo off
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" nbb_sync.py login
"%~dp0.venv\Scripts\python.exe" nbb_sync.py sync
pause
