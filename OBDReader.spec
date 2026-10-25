# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the OBD-II Reader. Produces two executables:
  dist/OBDReader-GUI.exe  (windowed Tkinter app, no console)
  dist/OBDReader-CLI.exe  (console app: all main.py flags)

Build from the project root:  pyinstaller OBDReader.spec
Requires: pip install pyinstaller
"""

import os

ROOT = os.path.abspath(SPECPATH)
block_cipher = None

common_kwargs = dict(
    # src/ must be importable so `features.*` resolves at analysis time.
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[],
    # Insurance: pyserial's port scanner and pint (via python-OBD) have both
    # been seen missed by analysis in some environments.
    hiddenimports=["serial.tools.list_ports", "pint"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

gui_a = Analysis(
    ["src/gui.py"],
    **common_kwargs,
)
gui_pyz = PYZ(gui_a.pure, gui_a.zipped_data, cipher=block_cipher)
gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    gui_a.binaries,
    gui_a.datas,
    [],
    name="OBDReader-GUI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX trips some antivirus heuristics; size is acceptable without it
    console=False,  # windowed: no console window behind the GUI
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

cli_a = Analysis(
    ["src/main.py"],
    **common_kwargs,
)
cli_pyz = PYZ(cli_a.pure, cli_a.zipped_data, cipher=block_cipher)
cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    cli_a.binaries,
    cli_a.datas,
    [],
    name="OBDReader-CLI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # CLI needs its console
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
