"""Offline release preparation, inventory and ZIP verification. Never reads user data."""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import ssl
import struct
import subprocess
import sys
import sysconfig
import zipfile
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def identity():
    from rpg_vkr import build_info

    return build_info


def prepare_release_profile(output):
    from dataclasses import asdict

    from rpg_vkr.deployment import ReleaseProfile

    mode = os.environ.get("DND_BUILD_PROFILE", "developer")
    gateway = os.environ.get("DND_GATEWAY_URL", "")
    discovery = os.environ.get("DND_DISCOVERY_URL", "")
    if mode == "tester" and not discovery and not gateway.startswith("https://"):
        raise ValueError("Tester Build requires the real HTTPS gateway address, never an API key")
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if subprocess.check_output(["git", "diff", "--name-only", "HEAD"], cwd=ROOT):
            commit += "-modified"
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    owner_binding = ""
    if mode == "owner":
        from rpg_vkr.owner_local import create_binding

        owner_binding = create_binding()
    profile = ReleaseProfile(
        mode,
        gateway,
        os.environ.get("DND_TEXT_MODEL", "~deepseek/deepseek-v4-flash-latest"),
        commit,
        discovery,
        os.environ.get("DND_DISCOVERY_KEY", ""),
        os.environ.get("DND_ACCOUNT_LOGIN", "") == "1",
        owner_binding,
    )
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    value = asdict(profile)
    if not profile.owner_binding:
        value.pop("owner_binding")
    if not profile.account_login:
        value.pop("account_login")
    if not profile.discovery:
        value.pop("discovery")
        value.pop("verification_key")
    output.write_text(json.dumps(value, indent=2), encoding="utf-8")
    return output


def prepare_bootstrap(output):
    source = os.environ.get("DND_BOOTSTRAP_FILE", "")
    if not source:
        return None
    if os.environ.get("DND_BUILD_PROFILE") != "tester":
        raise ValueError("Personal activation is allowed only in Tester Build")
    path = Path(source)
    if path.stat().st_size > 512:
        raise ValueError("Invalid personal activation file")
    value = json.loads(path.read_text(encoding="utf-8"))
    import re

    if set(value) != {"code"} or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value["code"]):
        raise ValueError("Invalid personal activation code")
    output = Path(output)
    output.write_text(json.dumps(value), encoding="utf-8")
    return output


def prepare_licenses(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    packages = []
    for name in (
        "PySide6-Essentials",
        "shiboken6",
        "pyinstaller",
        "pyinstaller-hooks-contrib",
        "cryptography",
        "cffi",
        "pycparser",
    ):
        installed = distribution(name)
        packages.append({"name": name, "version": installed.version})
        for item in installed.files or ():
            if "licenses" in item.parts and installed.locate_file(item).is_file():
                target = output / name / Path(item).name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(installed.locate_file(item), target)
    license_path = next(
        (
            p
            for p in (
                Path(sys.base_prefix) / "LICENSE.txt",
                Path(sysconfig.get_path("stdlib")) / "LICENSE.txt",
            )
            if p.is_file()
        ),
        None,
    )
    if license_path is None:
        raise ValueError("Python license file missing from build interpreter")
    shutil.copyfile(license_path, output / "PYTHON-LICENSE.txt")
    for file in (ROOT / "licenses/third-party").iterdir():
        if file.is_file():
            shutil.copyfile(file, output / file.name)
    inventory = {
        "python": platform.python_version(),
        "openssl": ssl.OPENSSL_VERSION,
        "packages": packages,
        "qt_sources": "https://code.qt.io/cgit/qt/qtbase.git/tag/?h=v"
        + distribution("PySide6-Essentials").version,
        "pyside_sources": "https://code.qt.io/cgit/pyside/pyside-setup.git/",
        "legal_status": (
            "Not a legal certification. Review LGPL redistribution and "
            "source availability before public distribution."
        ),
    }
    (output / "DEPENDENCIES.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    return [
        (str(p), "licenses/" + str(p.relative_to(output).parent))
        for p in output.rglob("*")
        if p.is_file()
    ]


def version_resource():
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo,
        StringFileInfo,
        StringStruct,
        StringTable,
        VarFileInfo,
        VarStruct,
        VSVersionInfo,
    )

    info = identity()
    version = tuple(map(int, info.VERSION.split("."))) + (0,)
    return VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=version,
            prodvers=version,
            mask=0x3F,
            flags=0,
            OS=0x40004,
            fileType=1,
            subtype=0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo(
                [
                    StringTable(
                        "041904B0",
                        [
                            StringStruct(k, v)
                            for k, v in {
                                "CompanyName": info.PUBLISHER,
                                "FileDescription": info.DESCRIPTION,
                                "FileVersion": info.VERSION,
                                "InternalName": info.APP_NAME,
                                "OriginalFilename": "DND-NCFU.exe",
                                "ProductName": info.DISPLAY_NAME,
                                "ProductVersion": info.VERSION,
                                "LegalCopyright": "DND-NCFU contributors, 2026",
                            }.items()
                        ],
                    )
                ]
            ),
            VarFileInfo([VarStruct("Translation", [0x419, 1200])]),
        ],
    )


def pe_gui_x64(path):
    raw = Path(path).read_bytes()
    if len(raw) < 128 or raw[:2] != b"MZ":
        return False
    offset = struct.unpack_from("<I", raw, 0x3C)[0]
    if offset + 96 > len(raw) or raw[offset : offset + 4] != b"PE\0\0":
        return False
    return (
        struct.unpack_from("<H", raw, offset + 4)[0] == 0x8664
        and struct.unpack_from("<H", raw, offset + 24)[0] == 0x20B
        and struct.unpack_from("<H", raw, offset + 24 + 68)[0] == 2
    )


def verify_bundle(folder, *, windows=True):
    from dataclasses import asdict

    from rpg_vkr.deployment import ReleaseProfile
    from rpg_vkr.resources import REQUIRED_RESOURCES

    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError("Bundle not found")
    exe = folder / ("DND-NCFU.exe" if windows else "DND-NCFU")
    if not exe.is_file() or (windows and not pe_gui_x64(exe)):
        raise ValueError("Missing x64 windowed application")
    release_profile = None
    config = folder / "_internal" / "release-profile.json"
    if config.exists():
        value = json.loads(config.read_text(encoding="utf-8"))
        release_profile = asdict(ReleaseProfile(**value))
        if (
            release_profile["mode"] == "tester"
            and not release_profile["discovery"]
            and not release_profile["gateway"].startswith("https://")
        ):
            raise ValueError("Tester package has no HTTPS service")
    bootstrap = folder / "_internal" / "tester-bootstrap.json"
    if bootstrap.exists():
        if (
            not release_profile
            or release_profile["mode"] != "tester"
            or not release_profile["discovery"]
            or bootstrap.stat().st_size > 512
        ):
            raise ValueError("Personal activation requires signed Tester profile")
        activation = json.loads(bootstrap.read_text(encoding="utf-8"))
        if set(activation) != {"code"} or not re.fullmatch(
            r"[A-Za-z0-9_-]{43}", activation["code"]
        ):
            raise ValueError("Invalid bundled personal activation")
    for relative in REQUIRED_RESOURCES:
        if not (folder / "_internal" / relative).is_file():
            raise ValueError("Missing bundled resource: " + relative)
    files = []
    for path in sorted(folder.rglob("*")):
        if path.is_symlink():
            raise ValueError("Symlink forbidden in release")
        if not path.is_file():
            continue
        rel = path.relative_to(folder).as_posix()
        if (
            any(
                part in {".venv", "tests", "saves", "secrets", "__pycache__"}
                for part in path.relative_to(folder).parts
            )
            or path.name.startswith(".env")
            or "credential.bin" in path.name
            or path.name
            in {
                "tester-access.bin",
                "developer-access.json",
                "tester-installation.bin",
                "routerai-key.bin",
                "signing-key.bin",
                "host-ready.json",
            }
            or (path.name.startswith("activation-") and path.suffix == ".bin")
            or path.name.endswith(".local.txt")
            or re.fullmatch(r"slot-[123]\.json", path.name)
            or path.suffix in {".sqlite3", ".sqlite", ".db"}
        ):
            raise ValueError("Forbidden release file: " + rel)
        raw = path.read_bytes()
        if re.search(rb"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_-]{20,}", raw):
            raise ValueError("Possible embedded provider credential in release file: " + rel)
        if path.name != "BUILD_MANIFEST.json":
            files.append(
                {"path": rel, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            )
    required = ("PYTHON-LICENSE.txt", "LGPL-3.0-only.txt", "GPL-3.0-only.txt", "DEPENDENCIES.json")
    for name in required:
        if not (folder / "_internal/licenses" / name).is_file():
            raise ValueError("Missing license: " + name)
    if windows:
        names = [Path(row["path"]).name.lower() for row in files]
        for pattern in (
            "python312.dll",
            "qt6core.dll",
            "qt6gui.dll",
            "qt6widgets.dll",
            "qt6network.dll",
            "qwindows.dll",
            "_sqlite3.pyd",
            "_ssl.pyd",
        ):
            if pattern not in names:
                raise ValueError("Missing Windows dependency: " + pattern)
    return {
        "version": identity().VERSION,
        "target": "windows-x64" if windows else "linux-test-only",
        "release_profile": release_profile,
        "files": files,
    }


def archive(folder, output, checks):
    folder = Path(folder)
    output = Path(output)
    checks = Path(checks)
    for name in ("self-check.json", "smoke-test.json"):
        report = json.loads((checks / name).read_text(encoding="utf-8"))
        if (
            report.get("ok") is not True
            or not report.get("frozen")
            or report.get("version") != identity().VERSION
        ):
            raise ValueError("Packaged application verification missing or failed")
    report = json.loads((checks / "smoke-test.json").read_text(encoding="utf-8"))
    if report.get("dpapi") != "native-roundtrip-passed" or not report.get(
        "platform", ""
    ).startswith("Windows"):
        raise ValueError("Native Windows smoke/DPAPI verification required")
    manifest = verify_bundle(folder)
    dest = folder / "verification"
    dest.mkdir(exist_ok=True)
    for name in ("self-check.json", "smoke-test.json"):
        shutil.copyfile(checks / name, dest / name)
    manifest = verify_bundle(folder)
    (folder / "BUILD_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                z.write(path, folder.name + "/" + path.relative_to(folder).as_posix())
    with zipfile.ZipFile(output) as z:
        for row in manifest["files"]:
            if hashlib.sha256(z.read(folder.name + "/" + row["path"])).hexdigest() != row["sha256"]:
                raise ValueError("Archive checksum mismatch")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(digest + "  " + output.name + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["version", "verify", "archive"])
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--checks", type=Path)
    args = parser.parse_args()
    if args.command == "version":
        print(identity().VERSION)
    elif args.command == "verify":
        print(json.dumps(verify_bundle(args.folder), indent=2))
    else:
        archive(args.folder, args.output, args.checks)


if __name__ == "__main__":
    main()
