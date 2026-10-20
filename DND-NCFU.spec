# Optional Windows onedir build. Only enumerated public resources enter the bundle.
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
a = Analysis(
    [str(root / 'scripts' / 'run_game.py')],
    pathex=[str(root / 'src')],
    binaries=[],
    datas=[
        (str(root / 'src/rpg_vkr/ui/assets'), 'rpg_vkr/ui/assets'),
        (str(root / 'data/catalog'), 'data/catalog'),
        (str(root / 'data/narrative'), 'data/narrative'),
        (str(root / 'prompts/master_system_prompt.txt'), 'prompts'),
        (str(root / 'LICENSES_AND_ATTRIBUTIONS.md'), '.'),
    ],
    hiddenimports=collect_submodules('rpg_vkr'),
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DND-NCFU',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DND-NCFU')
