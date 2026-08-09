# obylon_build.spec
import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

a = Analysis(
    ['sentinel_agent.py'], # <-- Make sure this matches your script's filename
    pathex=[],
    binaries=[],
    datas=[
        # CRITICAL: This bundles the Tesseract OCR binary and tessdata into the .exe
        # Ensure the 'tesseract_engine' folder is in the same directory as this .spec file before building.
        ('tesseract_engine', 'tesseract_engine'),
    ],
    hiddenimports=[
        'structlog', 'win32crypt', 'win32api', 'win32con',
        'ctypes', 'pynput', 'PIL', 'pytesseract', 'supabase', 'sqlite3',
        'psutil', 'cv2', 'websockets', 'asyncio' # <-- Added missing critical dependencies
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    a.datas,
    [],
    name='Obylon',           # <-- Renamed from Nexus
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # <-- Stealth Mode: No terminal window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,          # <-- Enforces Admin Elevation for Win32 Hooks
    icon='icon.ico',         # <-- (Optional) Place an icon.ico file in the directory, or comment this out
)