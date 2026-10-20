"""One read-only resource layout and a separate, writable user-data location."""

import os
import sys
from pathlib import Path

RESOURCE_ROOT = (
    Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
)
REQUIRED_RESOURCES = (
    "rpg_vkr/ui/assets/kingdom.png",
    "rpg_vkr/ui/assets/DND-NCFU.png",
    "rpg_vkr/ui/assets/DND-NCFU.ico",
    "data/catalog/seed-v1.json",
    "data/catalog/public-descriptions-v1.json",
    "data/narrative/genre-cards-v1.json",
    "prompts/master_system_prompt.txt",
)


def resource_path(relative):
    path = Path(relative)
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise ValueError("Resource path must be relative to the application.")
    if not getattr(sys, "frozen", False) and path.parts[0] == "rpg_vkr":
        return RESOURCE_ROOT / "src" / path
    return RESOURCE_ROOT / path


def data_directory():
    override = os.environ.get("RPG_VKR_DATA_DIR")
    frozen = getattr(sys, "frozen", False)
    if override:
        result = Path(override).expanduser()
        if frozen and not result.is_absolute():
            raise ValueError("Для EXE укажите абсолютный RPG_VKR_DATA_DIR.")
    elif frozen:
        result = (
            Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local/share"))) / "DND-NCFU"
        )
    else:
        result = RESOURCE_ROOT.parent / (RESOURCE_ROOT.name + "-data")
    if frozen:
        for forbidden in (RESOURCE_ROOT, Path(sys.executable).resolve().parent):
            if result.resolve().is_relative_to(forbidden.resolve()):
                raise ValueError("Папка данных должна находиться вне каталога программы.")
    return result
