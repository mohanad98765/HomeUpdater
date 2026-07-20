# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('../frontend/dist', 'frontend_dist'), ('alembic', 'alembic'), ('alembic.ini', '.'), ('VERSION', '.'), ('assets', 'assets'), ('loading.html', '.')]
binaries = []
hiddenimports = ['win32com', 'win32com.client', 'pythoncom', 'win32timezone', 'win32crypt', 'adb_shell']
# Native app window (pywebview + WebView2 via pythonnet) — dynamically imported.
hiddenimports += ['webview.platforms.edgechromium', 'webview.platforms.winforms',
                  'clr', 'clr_loader', 'clr_loader.ffi']
# Remote Windows updates (pywinrm) — auth stack pulled in dynamically.
hiddenimports += ['winrm', 'winrm.transport', 'requests_ntlm', 'xmltodict', 'spnego', 'sspilib']
hiddenimports += collect_submodules('sqlalchemy')
tmp_ret = collect_all('uvicorn')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('aiosqlite')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('alembic')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pystray')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('PIL')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('httpx')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('asyncssh')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cryptography')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# --- Native window shell (WebView2/edgechromium via pythonnet) ---
tmp_ret = collect_all('webview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('clr_loader')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pythonnet')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# --- Remote Windows updates (pywinrm + auth) ---
tmp_ret = collect_all('winrm')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('sspilib')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app_window.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
splash = Splash(
    'assets/splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

exe = EXE(
    pyz,
    a.scripts,
    splash,
    [],
    exclude_binaries=True,
    name='HomeUpdater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    uac_admin=True,  # embed a requireAdministrator manifest -> UAC on launch, so
    # Windows Update / winget / reboot actually have the privileges they need.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\HomeUpdater.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    splash.binaries,
    strip=False,
    upx=True,
    # UPX can corrupt managed/native interop DLLs -> blank window. Exclude them.
    upx_exclude=[
        'WebView2Loader.dll',
        'Microsoft.Web.WebView2.Core.dll',
        'Microsoft.Web.WebView2.WinForms.dll',
        'Microsoft.Web.WebView2.Wpf.dll',
        'Python.Runtime.dll',
    ],
    name='HomeUpdater',
)
