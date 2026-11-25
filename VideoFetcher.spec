# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata


project_dir = Path.cwd()

datas = [
    (str(project_dir / "templates"), "templates"),
    (str(project_dir / "static"), "static"),
    (str(project_dir / "tools"), "tools"),
    (str(project_dir / "third_party" / "LICENSE-GPL-3.0.txt"), "third_party"),
    (str(project_dir / "third_party" / "LICENSE-Douyin-TikTok-Download-API.txt"), "third_party"),
    (str(project_dir / "THIRD_PARTY_NOTICES.md"), "."),
]
ejs_datas, ejs_binaries, ejs_hiddenimports = collect_all("yt_dlp_ejs")
datas += ejs_datas + copy_metadata("yt-dlp")
# Conda-based venvs keep these Python extension dependencies outside Scripts/.
for name in ("ffi.dll", "sqlite3.dll"):
    dll = Path(sys.base_prefix) / "Library" / "bin" / name
    if dll.is_file():
        ejs_binaries.append((str(dll), "."))


a = Analysis(
    ["app.py"],
    pathex=[str(project_dir), str(project_dir / "vendor")],
    binaries=ejs_binaries,
    datas=datas,
    hiddenimports=ejs_hiddenimports + collect_submodules("yt_dlp"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="VideoFetcher",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="VideoFetcher",
)
