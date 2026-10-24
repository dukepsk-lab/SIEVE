@echo off
rem Forward paper-tracker launcher (research/PLAN.md section 10). Paper only: MT5 is used read-only (rates and one tick).
rem Run it any time after 16:05 New York time on a trading day; every run recomputes everything, so a missed day catches up.
rem Suitable as the action of a Task Scheduler task. This file does not register any task.
setlocal
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
cd /d "%~dp0..\.."
if errorlevel 1 exit /b 1
if not exist "research\forward\out" mkdir "research\forward\out"
echo ===== %date% %time% >> "research\forward\out\run.log"
python -m research.forward.track >> "research\forward\out\run.log" 2>&1
exit /b %ERRORLEVEL%
