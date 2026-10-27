# Existing onedir recipe, extended with explicit resources and release metadata.
import runpy
import sys
from pathlib import Path
from PyInstaller.compat import is_win
from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_submodules

root = Path(SPECPATH)
sys.path.insert(0, str(root / 'src'))
from rpg_vkr.resources import REQUIRED_RESOURCES, resource_path
helper = runpy.run_path(str(root / 'scripts/release_tools.py'))
license_data = helper['prepare_licenses'](Path(CONF['workpath']) / 'licenses')
profile = helper['prepare_release_profile'](Path(CONF['workpath']) / 'release-profile.json')
bootstrap = helper['prepare_bootstrap'](Path(CONF['workpath']) / 'tester-bootstrap.json')
personal = [(str(bootstrap), '.')] if bootstrap else []
resources = [(str(resource_path(relative)), str(Path(relative).parent)) for relative in REQUIRED_RESOURCES]
knowledge = root / 'data/approved_knowledge/index.json'
if knowledge.is_file():
    resources.append((str(knowledge), 'data/approved_knowledge'))
for name in ('manifest.json', 'cards.sqlite3'):
    corpus_resource = root / 'data/corpus_knowledge' / name
    if corpus_resource.is_file():
        resources.append((str(corpus_resource), 'data/corpus_knowledge'))
a = Analysis(
    [str(root / 'scripts/run_game.py')], pathex=[str(root / 'src')], binaries=[],
    datas=[*resources, *personal, (str(profile), '.'),
           (str(root / 'LICENSES_AND_ATTRIBUTIONS.md'), '.'), *license_data],
    hiddenimports=collect_submodules('rpg_vkr'), hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['tkinter', 'pytest', 'ruff', 'PyInstaller', 'training', 'torch', 'transformers', 'peft', 'bitsandbytes'], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DND-NCFU', debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False,
    icon=str(root / 'src/rpg_vkr/ui/assets/DND-NCFU.ico'),
    version=helper['version_resource']() if is_win else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='DND-NCFU')
