"""Owner-only offline data/training tools; never imported by the game client."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
