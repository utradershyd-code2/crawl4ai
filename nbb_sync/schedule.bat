@echo off
cd /d "%~dp0"
rem Creates (or repairs) the Task Scheduler task that syncs the panel every 15 minutes.
schtasks /Create /SC MINUTE /MO 15 /TN "NBB Panel Sync" /TR "\"%~dp0run_sync.bat\"" /F >nul || (echo Could not create the task. & pause & exit /b 1)
rem Wake the PC from sleep for each run, catch up a missed run, run on battery too, and never pile up runs.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10); Set-ScheduledTask -TaskName 'NBB Panel Sync' -Settings $s | Out-Null" && echo Done: the panel syncs every 15 minutes and wakes this PC from sleep to do it.
if "%~1"=="" pause
