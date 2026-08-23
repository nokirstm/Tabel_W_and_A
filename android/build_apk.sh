#!/usr/bin/env bash
# Сборка Android-версии в .apk на Linux (Ubuntu/Debian или WSL).
set -e
cd "$(dirname "$0")"

echo "=== Табель: сборка .apk ==="

if ! command -v buildozer >/dev/null 2>&1; then
    echo "[1/3] Устанавливаю buildozer..."
    sudo apt-get update
    sudo apt-get install -y git zip unzip openjdk-17-jdk python3-pip \
        autoconf libtool pkg-config zlib1g-dev libncurses-dev \
        libtinfo6 cmake libffi-dev libssl-dev
    pip3 install --user --upgrade buildozer cython==0.29.36 virtualenv
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "[2/3] Копирую общее ядро расчётов..."
cp ../core/timecard_core.py ../core/reports.py ./

echo "[3/3] Собираю apk (первый раз это 20-40 минут — скачивается Android SDK/NDK)..."
buildozer -v android debug

echo
echo "Готово. Файл:"
ls -1 bin/*.apk
