@echo off
setlocal EnableExtensions

REM Uninstalls the global uv tool.

where uv >nul 2>&1
if errorlevel 1 (
  echo uv not found. 1>&2
  exit /b 1
)

echo Uninstalling mcp-remote-py (uv tool)... 1>&2
uv tool uninstall mcp-remote-py >nul 2>&1

echo Done. 1>&2
exit /b 0
