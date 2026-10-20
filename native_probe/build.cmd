@echo off
setlocal
set "PROBE_DIR=%~dp0"
set "SDK_DIR=%PROBE_DIR%..\vendor\public-3dviewer-reference\thirdparty\3DCamera"
set "VCVARS=%ProgramFiles%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VCVARS%" (
  echo VS 2022 Community C++ tools were not found.
  exit /b 2
)
if not exist "%SDK_DIR%\include\h\system.h" (
  echo The pinned public SDK headers are missing.
  exit /b 3
)
call "%VCVARS%" >nul
if errorlevel 1 exit /b 4
if not exist "%PROBE_DIR%build" mkdir "%PROBE_DIR%build"
pushd "%PROBE_DIR%build"
cl /nologo /std:c++17 /EHsc /W4 /utf-8 /MD /I "%SDK_DIR%\include" "%PROBE_DIR%main.cpp" /Fe:public_sdk_probe.exe
set "BUILD_RESULT=%ERRORLEVEL%"
popd
exit /b %BUILD_RESULT%
