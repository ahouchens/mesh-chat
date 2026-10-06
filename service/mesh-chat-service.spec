# PyInstaller recipe used by scripts/build-sidecar.ps1.
from PyInstaller.utils.hooks import collect_all

rns_data, rns_binaries, rns_hidden = collect_all("RNS")
lxmf_data, lxmf_binaries, lxmf_hidden = collect_all("LXMF")

a = Analysis(
    ["entrypoint.py"],
    pathex=["src"],
    binaries=rns_binaries + lxmf_binaries,
    datas=rns_data + lxmf_data,
    hiddenimports=rns_hidden + lxmf_hidden,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mesh-chat-service",
    console=True,
    strip=False,
    upx=False,
)
