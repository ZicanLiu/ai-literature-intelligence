@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python scripts\start_comparison_workspace.py %*
) else (
  py -3 scripts\start_comparison_workspace.py %*
)
if errorlevel 1 (
  echo Startup failed. See the message above and docs\comparison_workspace\TEAM_PREVIEW.md.
  pause
  exit /b 1
)
