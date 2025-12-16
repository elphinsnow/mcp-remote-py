@echo off
setlocal EnableExtensions

REM Installs this project as a global user tool using uv.
REM Expected outcome: a runnable mcp-remote-py executable is installed.

pushd "%~dp0" >nul
if errorlevel 1 (
  echo Failed to change directory to project root. 1>&2
  exit /b 1
)

where uv >nul 2>&1
if errorlevel 1 (
  echo uv not found. Install it first: https://docs.astral.sh/uv/ 1>&2
  popd >nul
  exit /b 1
)

REM Ensure the tool bin dir matches the user's request (default: %USERPROFILE%\.local\bin)
if "%UV_TOOL_BIN_DIR%"=="" set "UV_TOOL_BIN_DIR=%USERPROFILE%\.local\bin"
if not exist "%UV_TOOL_BIN_DIR%" mkdir "%UV_TOOL_BIN_DIR%" >nul 2>&1

echo Installing mcp-remote-py into: %UV_TOOL_BIN_DIR% 1>&2

REM Editable install from local source so changes can be picked up easily during development.
REM --force makes this idempotent for re-runs.
uv tool install --editable . --force
if errorlevel 1 (
  echo uv tool install failed. 1>&2
  popd >nul
  exit /b 1
)

set "MCP_REMOTE_PY_PATH="
for /f "delims=" %%I in ('where mcp-remote-py 2^>nul') do (
  set "MCP_REMOTE_PY_PATH=%%I"
  goto :afterWhere
)

:afterWhere
if defined MCP_REMOTE_PY_PATH (
  echo OK: mcp-remote-py is on PATH: %MCP_REMOTE_PY_PATH% 1>&2
) else (
  echo Installed, but mcp-remote-py is not on PATH. 1>&2
  echo Add to your PATH: %UV_TOOL_BIN_DIR% 1>&2
)

echo Run: mcp-remote-py --help 1>&2

popd >nul
exit /b 0
