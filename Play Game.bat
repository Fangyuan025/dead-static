@echo off
title DEAD STATIC
chcp 65001 >nul 2>&1

:: Set console font and size (NSimSun, size 20, supports Chinese characters)
reg add "HKCU\Console\DEAD STATIC" /v "FaceName" /t REG_SZ /d "NSimSun" /f >nul 2>&1
reg add "HKCU\Console\DEAD STATIC" /v "FontSize" /t REG_DWORD /d 0x00140000 /f >nul 2>&1
reg add "HKCU\Console\DEAD STATIC" /v "CodePage" /t REG_DWORD /d 65001 /f >nul 2>&1
reg add "HKCU\Console\DEAD STATIC" /v "FontFamily" /t REG_DWORD /d 0x36 /f >nul 2>&1

:: Set window size larger for better readability
reg add "HKCU\Console\DEAD STATIC" /v "ScreenBufferSize" /t REG_DWORD /d 0x270078 /f >nul 2>&1
reg add "HKCU\Console\DEAD STATIC" /v "WindowSize" /t REG_DWORD /d 0x270078 /f >nul 2>&1

:: Relaunch in a new CMD window with the font settings applied
start "DEAD STATIC" cmd /k "chcp 65001 >nul & python "%~dp0game.py" & pause & exit"
