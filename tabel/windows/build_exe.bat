@echo off
chcp 65001 >nul
title Сборка Tabel.exe
echo ============================================
echo   Сборка Windows-версии «Табель» (.exe)
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [!] Python не найден. Установите Python 3.10+ с python.org
    echo     и отметьте галочку "Add Python to PATH".
    pause
    exit /b 1
)

echo [1/3] Установка зависимостей...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt
if errorlevel 1 goto err

echo.
echo [2/3] Сборка exe...
python -m PyInstaller tabel.spec --noconfirm --clean
if errorlevel 1 goto err

echo.
echo [3/3] Готово!
echo Файл: %cd%\dist\Tabel.exe
echo.
explorer "%cd%\dist"
pause
exit /b 0

:err
echo.
echo [!] Сборка завершилась с ошибкой. Прочитайте сообщение выше.
pause
exit /b 1
