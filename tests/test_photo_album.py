"""Real cached PNG, versions, public captions and cross-campaign isolation; no network."""

from PySide6.QtCore import QBuffer, QIODevice, QTimer
from PySide6.QtGui import QColor, QImage
from response_cases import new_session

from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_window import MainWindow
from rpg_vkr.visuals.context import scene_target


def png():
    image = QImage(30, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("gold"))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_album_real_cache_versions_viewer_restart_and_switch(qt_app, tmp_path):
    window = MainWindow(session=new_session(), saves=SaveSlots(tmp_path / "saves"))
    window.show()
    try:
        registry = window.visuals.registry
        target = scene_target(window._session)
        for _ in range(2):
            identity = registry.reserve(target.campaign, target.subject, "fake-model", 100, 10000)
            registry.describe(identity, target)
            registry.mark_submitted(identity)
            registry.complete(identity, png(), actual=100)
        window.open_section("Фотоальбом")
        album = window.photo_album
        album.refresh()
        assert album.list.count() == 1 and album.rows[0]["version"] == 2
        assert album.rows[0]["title"] == target.title
        album.history.setChecked(True)
        assert album.list.count() == 2
        before = window._session.to_dict()
        seen = []

        def close_viewer():
            from PySide6.QtWidgets import QLabel

            dialog = qt_app.activeModalWidget()
            seen.append(
                any(
                    label.pixmap() and not label.pixmap().isNull()
                    for label in dialog.findChildren(QLabel)
                )
            )
            dialog.accept()

        QTimer.singleShot(10, close_viewer)
        album.open_photo()
        assert seen == [True]
        assert window._session.to_dict() == before
        from rpg_vkr.visuals.registry import VisualRegistry

        restored = VisualRegistry(registry.directory)
        assert len(restored.campaign_assets(target.campaign, history=True)) == 2
        window._session = new_session()
        window._refresh_character()
        assert album.list.count() == 0 and not album.rows
        assert len(registry.campaign_assets(target.campaign, history=True)) == 2
    finally:
        window.close()
