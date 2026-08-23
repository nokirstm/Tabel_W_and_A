[app]

title = Табель
package.name = tabel
package.domain = ru.tabel

source.dir = .
source.include_exts = py,png,jpg,ttf,kv,json
source.include_patterns = assets/*

version = 1.0.0

requirements = python3==3.11,kivy

orientation = portrait
fullscreen = 0

presplash.filename = %(source.dir)s/assets/presplash.png
icon.filename = %(source.dir)s/assets/icon.png

android.presplash_color = #E7EDF3

# Разрешения: запись отчётов в общую папку (для «поделиться»)
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

android.api = 34
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = True
android.accept_sdk_license = True

# мягкая клавиатура не должна перекрывать поля ввода
android.manifest.orientation = portrait
android.softinput_mode = below_target

p4a.branch = master

[buildozer]
log_level = 2
warn_on_root = 0
