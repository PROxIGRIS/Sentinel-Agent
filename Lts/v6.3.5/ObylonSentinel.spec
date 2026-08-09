# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['sentinel_agent.py'],
    pathex=[],
    binaries=[],
    datas=[('tesseract_engine', 'tesseract_engine')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'pandas', 'numpy', 'matplotlib', 'PyQt5'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ObylonSentinel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Sentinel-Agent\\Lts\\v6.3.5\\assets\\icon.ico'],
)
