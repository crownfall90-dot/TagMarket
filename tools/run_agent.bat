@echo off
rem Compatibility for callers that already have a console.
"%SystemRoot%\System32\wscript.exe" //B //NoLogo "%~dp0run_agent.vbs"
