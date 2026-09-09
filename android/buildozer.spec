[app]

title = Тabelь — тест Android
package.name = tabel
package.domain = ru.tabel.test

source.dir = .
source.include_exts = py,png,jpg,ttf,kv,json
source.include_patterns = assets/*

version = 1.1.0
requirements = python3,kivy==2.1.0
orientation = portrait
fullscreen = 0

presplash.filename = %(source.dir)s/assets/presplash.png
icon.filename = %(source.dir)s/assets/icon.png
android.presplash_color = #E7EDF3
android.permissions =
android.api = 34
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a
android.allow_backup = False
android.accept_sdk_license = True
android.manifest.orientation = portrait
android.softinput_mode = below_target
p4a.branch = v2024.01.21
p4a.bootstrap = sdl2

[buildozer]
log_level = 2
warn_on_root = 0
