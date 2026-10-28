"""Check product documentation links, screenshot hashes and issue form IDs offline."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md"]
DOCS += [
    str(p.relative_to(ROOT))
    for directory in ("docs/repository", "docs/screenshots", "docs/releases", "docs/examples")
    for p in (ROOT / directory).glob("*.md")
]
DOCS += [
    "docs/" + name + ".md"
    for name in (
        "README",
        "tester-guide",
        "player-guide",
        "development",
        "owner-guide",
        "troubleshooting",
        "known-limitations",
        "architecture",
    )
]


def main():
    checked = 0
    for name in DOCS:
        path = ROOT / name
        text = re.sub(r"```.*?```", "", path.read_text(encoding="utf-8"), flags=re.S)
        for link in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)\)", text):
            if "://" in link or link.startswith("#"):
                continue
            target = (path.parent / unquote(link.split("#")[0])).resolve()
            if not target.exists():
                raise ValueError(f"Broken local link: {name} -> {link}")
            checked += 1
    manifest = json.loads((ROOT / "docs/screenshots/manifest.json").read_text())
    for row in manifest["screens"]:
        data = (ROOT / "docs/screenshots" / row["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["sha256"]
        assert row["width"] >= 800 and row["height"] >= 400
    for path in (ROOT / ".github/ISSUE_TEMPLATE").glob("*.yml"):
        if path.name == "config.yml":
            continue
        form = json.loads(path.read_text())  # JSON is valid YAML for GitHub Issue forms.
        ids = [row["id"] for row in form["body"] if "id" in row]
        assert ids and len(ids) == len(set(ids))
    print(
        f"Checked {len(DOCS)} documents, {checked} local links, "
        f"{len(manifest['screens'])} screenshot hashes and 3 issue forms."
    )


if __name__ == "__main__":
    main()
