#!/usr/bin/env bash
# Собирает только Android-тестовый APK. Windows-проект не используется.
set -euo pipefail
cd "$(dirname "$0")"
if ! command -v buildozer >/dev/null 2>&1; then
  echo 'Установите buildozer, затем повторите запуск.' >&2
  exit 1
fi
python3 -m py_compile main.py timecard_core.py reports.py
buildozer -v android debug
ls -1 bin/*.apk
