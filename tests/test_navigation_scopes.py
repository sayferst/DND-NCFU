"""Real navigation cannot expose uncreated worlds or escape settings into game tabs."""

from response_cases import new_session

from rpg_vkr.storage.slots import SaveSlots
from rpg_vkr.ui.main_window import MainWindow


def labels(window):
    return {window.section_tabs.tabText(i) for i in range(window.section_tabs.count())}


def test_api_settings_are_admin_only_and_have_no_game_tabs(qt_app, tmp_path):
    from rpg_vkr.deployment import ReleaseProfile

    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    window.release_profile = ReleaseProfile(
        mode="tester", gateway="https://example.org", account_login=True
    )
    window._account_name = "tester"
    window.show()
    try:
        window.open_section("Настройки")
        assert not window.api_settings_button.isVisible()
        window.open_section("Мастер")
        assert window.tabs.tabText(window.tabs.currentIndex()) == "Настройки"
        window._account_name = "admin"
        window._sync_navigation(window.tabs.currentIndex())
        assert window.api_settings_button.isVisible()
        window.api_settings_button.click()
        assert window.tabs.currentWidget() is window.developer_console
        assert labels(window) == {"API · admin", "Меню"}
    finally:
        window.close()


def test_no_world_blocks_game_even_via_raw_tabs(qt_app, tmp_path):
    window = MainWindow(saves=SaveSlots(tmp_path / "saves"))
    window.show()
    try:
        before = window._session.to_dict()
        for name in ("Приключение", "Герой", "Карта", "Инвентарь", "Энциклопедия мира"):
            window.open_section(name)
            assert window.tabs.tabText(window.tabs.currentIndex()) == "Главное меню"
        window.tabs.setCurrentIndex(0)
        assert window.tabs.tabText(window.tabs.currentIndex()) == "Главное меню"
        window.open_section("Настройки")
        assert labels(window) == {"Настройки", "Меню"}
        assert not window.resolution_panel.isVisible()
        assert window._session.to_dict() == before
    finally:
        window.close()


def test_world_tabs_and_standalone_pages_have_separate_scopes(qt_app, tmp_path):
    window = MainWindow(session=new_session(), saves=SaveSlots(tmp_path / "saves"))
    window.show()
    try:
        window.resume_session()
        before = window._session.to_dict(), window._session.dice.checkpoint()
        assert labels(window) == {
            "Приключение",
            "Герой",
            "Инвентарь",
            "Дневник",
            "Карта",
            "Энциклопедия",
            "Меню",
        }
        window.open_section("Карта")
        assert window.tabs.tabText(window.tabs.currentIndex()) == "Карта"
        window.open_section("Главное меню")
        window.open_section("Настройки")
        window.open_section("Приключение")
        window.tabs.setCurrentIndex(0)
        assert window.tabs.tabText(window.tabs.currentIndex()) == "Настройки"
        assert labels(window) == {"Настройки", "Меню"}
        window.open_section("Главное меню")
        menu = window.tabs.currentWidget()
        for name in ("Сохранения", "Фотоальбом"):
            menu.menu_actions[name].click()
            assert labels(window) == {name, "Меню"}
            window.open_section("Главное меню")
        assert before == (window._session.to_dict(), window._session.dice.checkpoint())
    finally:
        window.close()
