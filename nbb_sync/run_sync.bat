@echo off
cd /d "%~dp0"
call .venv\Scripts\activate
echo ==== %date% %time% >> sync_log.txt
python nbb_sync.py sync >> sync_log.txt 2>&1
