"""Bundled resources are read-only; user data is resolved separately."""

import sys
from pathlib import Path

RESOURCE_ROOT = (
    Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
)
