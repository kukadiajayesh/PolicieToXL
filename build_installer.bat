@echo off
:: Builds the Windows installer (InsurancePolicyExtractorSetup.exe) from source.
:: Bundles both x64 and x86 builds - requires a 32-bit Python interpreter too,
:: see build_installer.ps1's -Python32Path parameter.
:: Double-click to build with version 1.0.0, or pass a version: build_installer.bat 1.2.0
powershell -ExecutionPolicy Bypass -File "%~dp0build_installer.ps1" %1
if %ERRORLEVEL% neq 0 pause
