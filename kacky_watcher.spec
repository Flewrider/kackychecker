# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Kacky Watcher.
Creates a windowed Windows EXE with all dependencies bundled.
"""

import os
import sys
from pathlib import Path

block_cipher = None

# Collect all Python files
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.scrolledtext',
        'tkinter.messagebox',
        'requests',
        'beautifulsoup4',
        'bs4',
        'playwright',
        'playwright.sync_api',
        'playwright._impl._driver',
        'playwright._impl._cli',
        'plyer',
        'plyer.platforms',
        'plyer.platforms.win',
        'plyer.platforms.win.notification',
        'windows_notifications',
        'greenlet',
        'path_utils',
        'playwright_installer',
        'config',
        'settings_manager',
        'map_status_manager',
        'watchlist_manager',
        'watcher_core',
        'watcher_state',
        'schedule_fetcher',
        'schedule_parser',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'pytest',
        'test',
        'tests',
    ],
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
    name='KackyWatcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Windowed mode (no console)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Add icon path here if you have one
)

