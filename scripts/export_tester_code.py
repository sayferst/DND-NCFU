"""Export an already issued owner grant; never issue a new grant or reset its budget."""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id")
    args = parser.parse_args()
    if os.name != "nt" or not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", args.id):
        parser.error("Run on the owner's Windows PC with a valid tester ID.")
    from rpg_vkr.storage.connection import load_secret

    root = Path(os.environ["LOCALAPPDATA"]) / "DND-NCFU-Host"
    code = load_secret(root / ("activation-" + args.id + ".bin"))
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", code or ""):
        print(
            "Existing grant not found. Issue it using tester_host.cmd build "
            "in the development checkout."
        )
        return 1
    target = Path(__file__).resolve().parents[1] / "dist" / (args.id + "-access.txt")
    target.parent.mkdir(exist_ok=True)
    target.write_text(code + "\n", encoding="utf-8")
    print(
        "Send this file privately to the designated tester; never attach it to a release: "
        + str(target)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
