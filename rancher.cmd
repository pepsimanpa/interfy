@echo off
setlocal EnableExtensions
rem Interfy on Rancher Desktop for Windows.
rem Usage: rancher.cmd [up^|down^|ps^|logs] [moby^|containerd]
rem Examples: rancher.cmd up moby
rem           rancher.cmd up containerd
rem No data volumes are removed by this launcher.

pushd "%~dp0" || exit /b 1
set "ACTION=%~1"
set "ENGINE=%~2"
if "%ACTION%"=="" set "ACTION=up"
if "%ENGINE%"=="" set "ENGINE=moby"

where rdctl >nul 2>&1
if errorlevel 1 (
  echo ERROR: Rancher Desktop CLI "rdctl" not found.
  echo Install and start Rancher Desktop, then open a NEW terminal.
  goto error
)

if /i "%ENGINE%"=="moby" (
  set "CLI=docker"
  goto engine_ready
)
if /i "%ENGINE%"=="containerd" (
  set "CLI=nerdctl"
  goto engine_ready
)
echo ERROR: Engine must be moby or containerd.
goto error

:engine_ready
where %CLI% >nul 2>&1
if errorlevel 1 (
  echo ERROR: %CLI% not found. Check the Rancher Desktop container engine setting.
  goto error
)
%CLI% info >nul 2>&1
if errorlevel 1 (
  echo ERROR: %CLI% cannot connect to a running container engine.
  echo Start Rancher Desktop and select the matching Container Engine.
  goto error
)

if /i "%ACTION%"=="up" (
  echo Starting Interfy on Rancher Desktop ^(%ENGINE%^)...
  %CLI% compose -f docker-compose.yml -f compose.rancher.yml up -d --build
  goto result
)
if /i "%ACTION%"=="down" (
  echo Stopping Interfy; persistent database volume will be kept...
  %CLI% compose -f docker-compose.yml -f compose.rancher.yml down
  goto result
)
if /i "%ACTION%"=="ps" (
  %CLI% compose -f docker-compose.yml -f compose.rancher.yml ps
  goto result
)
if /i "%ACTION%"=="logs" (
  %CLI% compose -f docker-compose.yml -f compose.rancher.yml logs --tail=100
  goto result
)
echo ERROR: Action must be up, down, ps or logs.
goto error

:result
set "CODE=%ERRORLEVEL%"
if "%CODE%"=="0" if /i "%ACTION%"=="up" (
  echo.
  echo Interfy: http://localhost:3000
  echo API:     http://localhost:8000/docs
)
popd
exit /b %CODE%

:error
popd
exit /b 1
