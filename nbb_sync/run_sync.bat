@echo off
cd /d "%~dp0"
echo ==== %date% %time% >> sync_log.txt
"%~dp0.venv\Scripts\python.exe" nbb_sync.py sync >> sync_log.txt 2>&1
