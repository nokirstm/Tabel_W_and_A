# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller-спецификация для сборки Tabel.exe
Сборка:  pyinstaller tabel.spec --noconfirm --clean
"""
import os

block_cipher = None
ROOT = os.path.abspath(os.getcwd())          # папка windows/
CORE = os.path.abspath(os.path.join(ROOT, "..", "core"))

a = Analysis(
    ["app.py"],
    pathex=[ROOT, CORE],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "assets", "icon.ico"), "assets"),
        (os.path.join(ROOT, "assets", "icon.png"), "assets"),
        (os.path.join(ROOT, "assets", "DejaVuSans.ttf"), "assets"),
        (os.path.join(ROOT, "assets", "DejaVuSans-Bold.ttf"), "assets"),
    ],
    hiddenimports=["timecard_core", "reports", "ui_kit", "openpyxl", "reportlab"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "numpy", "pandas", "PyQt5", "PySide2", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="Tabel",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                 # без чёрного окна консоли
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    version_info=None,
)
