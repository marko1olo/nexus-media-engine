@echo off
:: Включаем поддержку кодировки UTF-8 для красивого текста
chcp 65001 >nul
title Immersion Nexus 5.5 // Florence-2 AI Russian Captioner
color 0D

echo ==============================================================================
echo       IMMERSION NEXUS 5.5 // FLORENCE-2 AI RUSSIAN CAPTIONER (CUDA)
echo ==============================================================================
echo.

cd /d "%~dp0"

:: Проверяем Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ОШИБКА] Python не найден в PATH!
    pause
    exit /b
)

:: Проверяем, запущен ли уже фоновый сервер
curl -s -m 1 http://127.0.0.1:5000/api/captioner/status >nul 2>&1
if %errorlevel% equ 0 (
    echo [*] Фоновый сервер уже активен и обрабатывает картинки на GPU!
    echo [*] Открываем веб-интерфейс в браузере...
    start http://127.0.0.1:5000
    timeout /t 3 >nul
    exit /b
)

echo [*] Запуск локального сервера галереи и фонового нейро-разметчика...
echo [*] Браузер откроется автоматически через 3 секунды...
echo.
echo ==============================================================================
echo   СЕРВЕР РАБОТАЕТ В РЕЖИМЕ АВТОВОССТАНОВЛЕНИЯ.
echo   ДЛЯ ОСТАНОВКИ ПРОСТО ЗАКРОЙТЕ ЭТО ОКНО.
echo ==============================================================================
echo.

start cmd /c "timeout /t 3 >nul & start http://127.0.0.1:5000"

:RESTART_LOOP
python app.py
echo.
echo [!] Процесс app.py завершился. Автоматический перезапуск через 3 секунды...
timeout /t 3 >nul
goto RESTART_LOOP