@echo off
cd /d "%~dp0"
call .venv\Scripts\activate
python nbb_sync.py login
python nbb_sync.py sync
pause
