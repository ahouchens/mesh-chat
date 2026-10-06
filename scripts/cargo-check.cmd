@echo off
setlocal
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat" -arch=x64 -host_arch=x64
if errorlevel 1 exit /b %errorlevel%
pushd "%~dp0..\src-tauri"
"%USERPROFILE%\.cargo\bin\cargo.exe" check --locked
set RESULT=%errorlevel%
popd
exit /b %RESULT%

