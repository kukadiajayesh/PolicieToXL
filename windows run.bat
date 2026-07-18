@echo off
cd /d "%~dp0"
echo CWD=%cd%
dir /b run.bat
call run.bat
