# PyInstaller recipe used by scripts/build-sidecar.ps1.
from PyInstaller.utils.hooks import collect_all
import runpy
from pathlib import Path

materials = runpy.run_path(str(Path(SPECPATH).parent / "scripts/native_runtime_materials.py"))
runtime_material_datas = materials["pyinstaller_datas"]()

rns_data, rns_binaries, rns_hidden = collect_all("RNS")
lxmf_data, lxmf_binaries, lxmf_hidden = collect_all("LXMF")
certifi_data, certifi_binaries, certifi_hidden = collect_all("certifi")
av_data, av_binaries, av_hidden = collect_all("av")
aiortc_data, aiortc_binaries, aiortc_hidden = collect_all("aiortc")

a = Analysis(
    ["entrypoint.py"],
    pathex=["src"],
    binaries=rns_binaries + lxmf_binaries + certifi_binaries + av_binaries + aiortc_binaries,
    datas=rns_data + lxmf_data + certifi_data + av_data + aiortc_data + runtime_material_datas,
    hiddenimports=rns_hidden + lxmf_hidden + certifi_hidden + av_hidden + aiortc_hidden,
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
