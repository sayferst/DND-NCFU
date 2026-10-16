"""Launch from the checkout, including when called from another directory."""

import sys
from pathlib import Path


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from rpg_vkr.app import main as run_app

    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
