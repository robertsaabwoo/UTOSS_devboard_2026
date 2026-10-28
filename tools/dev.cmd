@echo off
rem Windows entry point that does not care about PowerShell execution policy.
rem
rem   tools\dev.cmd sim --module examples
rem   tools\dev.cmd lint
rem   tools\dev.cmd synth --only example_fifo
rem   tools\dev.cmd all
rem
rem A fresh Windows shell has every execution-policy scope Undefined, which
rem means Restricted, which means `.\tools\dev.ps1` fails outright with
rem UnauthorizedAccess. A .cmd file is not a PowerShell script, so it runs
rem regardless -- and it then launches dev.ps1 with a process-scoped bypass.
rem
rem The bypass applies ONLY to this one child process. It changes no machine or
rem user setting and leaves the system exactly as it was, which is why this is
rem preferable to telling every contributor to run Set-ExecutionPolicy.
rem
rem -NoProfile as well, so a contributor's personal profile cannot change the
rem behaviour of a build.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
exit /b %ERRORLEVEL%
