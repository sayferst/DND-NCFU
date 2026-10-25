"""The UI lock is local, revocable for the session, and independent of server access."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QLineEdit, QPushButton

from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.developer_access import DeveloperAccess
from rpg_vkr.ui.main_window import MainWindow


def test_personal_keys_unlock_tester_panels_and_ignore_late_discovery(qt_app, tmp_path):
    from rpg_vkr.deployment import ReleaseProfile
    from rpg_vkr.ui.tester_discovery import ConnectionWorker

    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    try:
        console = window.developer_console
        window.release_profile = ReleaseProfile(mode="tester")
        for page in console.originals.values():
            page.setEnabled(False)
        console.use_personal_api()
        assert not window.cloud_key.isEnabled()  # Authentication remains required.
        enter_developer(qt_app, window)
        console.personal_api_button.click()
        assert window.release_profile.mode == "developer"
        window.cloud_key.setText("synthetic-master")
        assert window.cloud_key.isEnabled() and not window.cloud_key.isReadOnly()
        window.artist_panel.shared_key.setChecked(False)
        assert window.artist_panel.key_input.isEnabled()
        window.artist_panel.key_input.setText("synthetic-artist")
        assert window.cloud_key.text() == "synthetic-master"
        worker = ConnectionWorker(window)
        worker.timer.stop()
        worker.apply({"endpoint": "https://example.org/api/v1", "token": "unused"})
        assert window._tester_endpoint == "" and window._tester_token == ""
        assert not window.visuals.worker.transport.gateway
        assert window.cloud_key.text() == "synthetic-master"
    finally:
        window.close()


def enter_developer(qt_app, window, password="995539", name="Разработчик"):
    def fill():
        dialog = qt_app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        dialog.findChild(QLineEdit).setText(password)
        next(b for b in dialog.findChildren(QPushButton) if b.text() == "Войти").click()

    QTimer.singleShot(0, fill)
    window.open_section(name)


def test_attempt_limit_change_and_restart(tmp_path):
    now = [0.0]
    access = DeveloperAccess(tmp_path / "access.json", lambda: now[0])
    for _ in range(5):
        assert not access.login("wrong")
    assert not access.login("995539")
    now[0] = 31
    assert access.login("995539")
    access.change_password("995539", "new-owner-password")
    assert "new-owner-password" not in access.path.read_text()
    reopened = DeveloperAccess(access.path)
    assert not reopened.authorized and not reopened.login("995539")
    assert reopened.login("new-owner-password")
    reopened.logout()
    assert not reopened.authorized


def test_corrupt_verifier_does_not_restore_default(tmp_path):
    path = tmp_path / "access.json"
    path.write_text("{}")
    assert not DeveloperAccess(path).login("995539")


def test_real_password_dialog_gates_direct_navigation_and_logout(qt_app, tmp_path):
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    window.show()
    try:
        console = window.developer_console
        assert not console.access.authorized
        assert "Мастер" not in [window.tabs.tabText(i) for i in range(window.tabs.count())]
        before = window._session.to_dict()
        QTimer.singleShot(0, lambda: qt_app.activeModalWidget().reject())
        window.open_section("Мастер")
        assert not console.access.authorized and window.tabs.currentWidget() is not console
        window.tabs.setCurrentWidget(console)  # Bypass button; handler must still enforce access.
        assert window.tabs.currentWidget() is not console
        enter_developer(qt_app, window, name="Мастер")
        assert console.access.authorized and window.tabs.currentWidget() is console
        assert console.pages.currentWidget() is console.originals["Мастер"]
        console.logout()
        assert not console.access.authorized
        window.tabs.setCurrentWidget(console)
        assert window.tabs.currentWidget() is not console
        assert before == window._session.to_dict()
    finally:
        window.close()
