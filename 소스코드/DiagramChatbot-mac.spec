# -*- mode: python ; coding: utf-8 -*-
# macOS .app 빌드 전용 스펙 (윈도우용 DiagramChatbot.spec와 별도)
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
for pkg in ('pymupdf', 'resvg_py'):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pandas', 'scipy', 'pyarrow', 'pygame', 'matplotlib', 'numpy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DiagramChatbot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
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
    name='DiagramChatbot',
)

app = BUNDLE(
    coll,
    name='DiagramChatbot.app',
    icon=None,
    bundle_identifier='com.goldring.diagramchatbot',
    info_plist={
        'CFBundleName': 'DiagramChatbot',
        'CFBundleDisplayName': '도식화 챗봇',
        'CFBundleShortVersionString': '0.3.5',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
    },
)
