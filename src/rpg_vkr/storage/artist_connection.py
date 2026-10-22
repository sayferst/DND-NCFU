"""Nonsecret artist preferences; API credentials belong in a separate DPAPI envelope."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from rpg_vkr.ui.workspace_tools import atomic_text
from rpg_vkr.visuals.policy import FLUX, RECRAFT


@dataclass(frozen=True)
class ArtistPreferences:
    shared_key: bool = True
    remember_key: bool = False
    selected_model: str = RECRAFT

    def __post_init__(self):
        if (
            type(self.shared_key) is not bool
            or type(self.remember_key) is not bool
            or self.selected_model not in {RECRAFT, FLUX}
        ):
            raise ValueError("Некорректные настройки подключения Художника.")

    @classmethod
    def load(cls, path):
        try:
            path = Path(path)
            if path.stat().st_size > 4096:
                return cls()
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path):
        atomic_text(Path(path), json.dumps(asdict(self), indent=2) + "\n")
