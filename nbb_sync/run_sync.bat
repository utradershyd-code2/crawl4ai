@echo off
cd /d "%~dp0"
python nbb_sync.py sync >> sync_log.txt 2>&1
