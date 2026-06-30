@echo off
:: Windows launcher — delegates to run.ps1
:: Double-click this file or run it from Command Prompt.
powershell -ExecutionPolicy Bypass -File "%~dp0run.ps1"
if %ERRORLEVEL% neq 0 pause
