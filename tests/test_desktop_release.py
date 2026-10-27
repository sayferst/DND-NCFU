"""Offline desktop startup and release safety tests; no real provider calls."""

import json
import struct
import sys

import pytest
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest

from rpg_vkr import resources
from rpg_vkr.diagnostics import record_error
from rpg_vkr.self_check import check_resources, write_report
from rpg_vkr.ui.loading_screen import LoadingScreen
from scripts.release_tools import archive, pe_gui_x64, verify_bundle


def pe_bytes(*, machine=0x8664, subsystem=2):
    raw = bytearray(300)
    raw[:2] = b"MZ"
    struct.pack_into("<I", raw, 0x3C, 128)
    raw[128:132] = b"PE\0\0"
    struct.pack_into("<H", raw, 132, machine)
    struct.pack_into("<H", raw, 152, 0x20B)
    struct.pack_into("<H", raw, 220, subsystem)
    return bytes(raw)


def test_icon_has_all_native_sizes_and_decodable_frames():
    path = resources.resource_path("rpg_vkr/ui/assets/DND-NCFU.ico")
    data = path.read_bytes()
    _, kind, count = struct.unpack_from("<HHH", data)
    sizes = []
    for i in range(count):
        width, _, _, _, _, _, length, offset = struct.unpack_from("<BBBBHHII", data, 6 + i * 16)
        width = width or 256
        sizes.append(width)
        image = QImage.fromData(data[offset : offset + length])
        assert not image.isNull() and image.width() == width
    assert kind == 1 and {16, 32, 48, 256} <= set(sizes)


def test_resource_probe_ignores_user_override_and_does_not_touch_saves(
    qt_app, tmp_path, monkeypatch
):
    monkeypatch.setenv("RPG_VKR_DATA_DIR", str(tmp_path / "data"))
    report = check_resources()
    assert report["ok"] and report["network_requests"] == 0 and report["qt_tls"]
    assert not (tmp_path / "data").exists()
    destination = tmp_path / "report.json"
    write_report(destination, report)
    with pytest.raises(FileExistsError):
        write_report(destination, report)


@pytest.mark.parametrize(
    "relative",
    [
        "../outside",
        "data/../../outside",
        "/absolute",
        r"\outside",
        r"C:\outside",
        "C:relative",
        r"\\server\share\file",
        r"\\?\C:\outside",
        r"data\..\outside",
        "",
        ".",
    ],
)
def test_resource_paths_cannot_escape_application(relative):
    with pytest.raises(ValueError):
        resources.resource_path(relative)


@pytest.mark.parametrize("relative", resources.REQUIRED_RESOURCES)
def test_resource_separators_resolve_to_the_same_existing_file(relative):
    path = resources.resource_path(relative)
    assert path.is_file()
    assert resources.resource_path(relative.replace("/", "\\")) == path


def test_frozen_resource_paths_use_bundle_root(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(resources, "RESOURCE_ROOT", tmp_path)
    assert resources.resource_path(r"rpg_vkr\ui\assets\DND-NCFU.ico") == (
        tmp_path / "rpg_vkr" / "ui" / "assets" / "DND-NCFU.ico"
    )


def test_missing_resource_is_a_real_error_without_asserts(qt_app, monkeypatch, tmp_path):
    monkeypatch.setattr(resources, "RESOURCE_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        check_resources()


@pytest.mark.parametrize("choice", ["install", "internal", "relative"])
def test_frozen_data_cannot_write_inside_installation(tmp_path, monkeypatch, choice):
    install = tmp_path / "Program Files"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "DND-NCFU.exe"))
    monkeypatch.setattr(resources, "RESOURCE_ROOT", install / "_internal")
    selected = {
        "install": str(install / "data"),
        "internal": str(install / "_internal/data"),
        "relative": "data",
    }[choice]
    monkeypatch.setenv("RPG_VKR_DATA_DIR", selected)
    with pytest.raises(ValueError):
        resources.data_directory()


def test_external_data_override_is_stable_across_cwd_and_update(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("RPG_VKR_DATA_DIR", str(tmp_path / "Прежние данные"))
    for name in ["Version 1", "Version 2"]:
        install = tmp_path / name
        install.mkdir()
        monkeypatch.setattr(sys, "executable", str(install / "DND-NCFU.exe"))
        monkeypatch.setattr(resources, "RESOURCE_ROOT", install / "_internal")
        monkeypatch.chdir(install)
        assert resources.data_directory() == tmp_path / "Прежние данные"


def test_crash_report_never_serializes_exception_message_key_or_campaign(tmp_path, monkeypatch):
    monkeypatch.setenv("RPG_VKR_DATA_DIR", str(tmp_path))
    try:
        raise RuntimeError("sk-secretkey-and-private-character-backstory")
    except RuntimeError as error:
        path = record_error(error)
    text = path.read_text(encoding="utf-8")
    assert "RuntimeError" in text and "sk-secret" not in text and "backstory" not in text
    assert json.loads(text)["frames"]
    assert list(tmp_path.iterdir()) == [tmp_path / "logs"]


def test_loading_animation_ticks_but_never_fakes_progress(qt_app):
    splash = LoadingScreen()
    try:
        splash.show()
        splash.set_stage(35, "Ресурсы мира")
        before = splash.elapsed.elapsed()
        QTest.qWait(80)
        assert splash.elapsed.elapsed() > before and splash.value == 35
        splash.set_stage(20, "Повторная проверка")
        assert splash.value == 35 and not splash.grab().isNull()
    finally:
        splash.close()
    assert not splash.timer.isActive()


@pytest.mark.parametrize(
    "machine,subsystem,valid", [(0x8664, 2, True), (0x14C, 2, False), (0x8664, 3, False)]
)
def test_pe_accepts_only_windowed_x64(tmp_path, machine, subsystem, valid):
    path = tmp_path / "game.exe"
    path.write_bytes(pe_bytes(machine=machine, subsystem=subsystem))
    assert pe_gui_x64(path) is valid


@pytest.fixture
def fake_bundle(tmp_path):
    bundle = tmp_path / "DND-NCFU"
    bundle.mkdir()
    (bundle / "DND-NCFU.exe").write_bytes(pe_bytes())
    for relative in resources.REQUIRED_RESOURCES:
        path = bundle / "_internal" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"public resource")
    licenses = bundle / "_internal/licenses"
    licenses.mkdir()
    for name in (
        "PYTHON-LICENSE.txt",
        "LGPL-3.0-only.txt",
        "GPL-3.0-only.txt",
        "DEPENDENCIES.json",
    ):
        (licenses / name).write_text("public notice")
    for name in (
        "python312.dll",
        "qt6core.dll",
        "qt6gui.dll",
        "qt6widgets.dll",
        "qt6network.dll",
        "qwindows.dll",
        "_sqlite3.pyd",
        "_ssl.pyd",
    ):
        (bundle / "_internal" / name).write_bytes(b"synthetic dll")
    return bundle


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        "artist-credential.bin",
        "tester-access.bin",
        "developer-access.json",
        "master_system_prompt.local.txt",
        "slot-1.json",
        "campaigns.sqlite3",
    ],
)
def test_release_audit_rejects_user_files(fake_bundle, name):
    (fake_bundle / name).write_text("private")
    with pytest.raises(ValueError, match="Forbidden"):
        verify_bundle(fake_bundle)


def test_release_audit_checks_resource_inventory_and_credentials(fake_bundle):
    report = verify_bundle(fake_bundle)
    assert report["target"] == "windows-x64" and report["files"]
    (fake_bundle / "accidental.txt").write_text("sk-123456789012345678901234567890")
    with pytest.raises(ValueError, match="credential"):
        verify_bundle(fake_bundle)


def test_archive_requires_native_packaged_evidence(fake_bundle, tmp_path):
    checks = tmp_path / "checks"
    checks.mkdir()
    from rpg_vkr.build_info import VERSION

    for name in ("self-check", "smoke-test"):
        (checks / (name + ".json")).write_text(
            json.dumps(
                {
                    "ok": True,
                    "frozen": True,
                    "version": VERSION,
                    "platform": "Linux",
                    "dpapi": "unavailable",
                }
            )
        )
    with pytest.raises(ValueError, match="Native Windows"):
        archive(fake_bundle, tmp_path / "game.zip", checks)
    assert not (tmp_path / "game.zip").exists()


def test_archive_checks_every_file_and_keeps_verification_reports(fake_bundle, tmp_path):
    """Synthetic PE/reports exercise the archiver, never claim a Windows execution."""
    import hashlib
    import zipfile

    from rpg_vkr.build_info import VERSION

    checks = tmp_path / "checks"
    checks.mkdir()
    for mode in ("self-check", "smoke-test"):
        (checks / (mode + ".json")).write_text(
            json.dumps(
                {
                    "ok": True,
                    "frozen": True,
                    "version": VERSION,
                    "platform": "Windows-synthetic-test-only",
                    "dpapi": "native-roundtrip-passed",
                }
            ),
            encoding="utf-8",
        )
    destination = tmp_path / "portable.zip"
    archive(fake_bundle, destination, checks)
    with zipfile.ZipFile(destination) as bundled:
        manifest = json.loads(bundled.read("DND-NCFU/BUILD_MANIFEST.json"))
        for item in manifest["files"]:
            assert (
                hashlib.sha256(bundled.read("DND-NCFU/" + item["path"])).hexdigest()
                == item["sha256"]
            )
        assert "DND-NCFU/verification/smoke-test.json" in bundled.namelist()
    assert (
        destination.with_suffix(".zip.sha256")
        .read_text()
        .startswith(hashlib.sha256(destination.read_bytes()).hexdigest())
    )


def test_real_source_smoke_mode_is_isolated_and_makes_only_loopback_requests(tmp_path):
    import os
    import subprocess
    from pathlib import Path

    launcher = Path(__file__).resolve().parents[1] / "scripts/run_game.py"
    report = tmp_path / "report.json"
    environment = os.environ.copy()
    environment["RPG_VKR_DATA_DIR"] = str(tmp_path / "untouched-real-data")
    result = subprocess.run(
        [sys.executable, str(launcher), "--smoke-test", "--report", str(report)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        timeout=30,
    )
    failure = report.read_text(encoding="utf-8") if report.is_file() else "No diagnostic report"
    assert result.returncode == 0, (result.stderr, failure)
    actual = json.loads(report.read_text(encoding="utf-8"))
    assert actual["ok"] and actual["references"] and actual["save_sqlite"] and actual["rng"]
    assert actual["loopback_posts"] == 4 and actual["network_requests"] == 6
    assert actual["world_creation"] and actual["world_brief_preserved"]
    assert actual["external_model_requests"] == 0
    assert not (tmp_path / "untouched-real-data").exists()


def test_failed_release_probe_exposes_safe_frames_without_exception_message(tmp_path, monkeypatch):
    from rpg_vkr import app, bootstrap

    marker = "private-provider-credential-must-not-be-logged"

    def fail():
        raise RuntimeError(marker)

    report = tmp_path / "failure.json"
    monkeypatch.setenv("RPG_VKR_DATA_DIR", str(tmp_path / "isolated-data"))
    monkeypatch.setattr(sys, "argv", ["game", "--self-check", "--report", str(report)])
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(app, "main", fail)
    assert bootstrap.launch() == 1
    text = report.read_text(encoding="utf-8")
    value = json.loads(text)
    assert value["ok"] is False and value["error_type"] == "RuntimeError"
    assert value["frames"][-1]["function"] == "fail"
    assert marker not in text and str(tmp_path) not in text
