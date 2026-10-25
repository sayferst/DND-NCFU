"""Navigation scopes: game pages require a world; standalone pages return through menu."""

GAME = {"Приключение", "Герой", "Инвентарь", "Дневник", "Карта", "Энциклопедия мира"}
STANDALONE = {"Настройки", "Сохранения", "Фотоальбом"}
TECHNICAL = {"Мастер", "Рассказчик", "Художник", "Разработчик"}


def allowed(window, target):
    if window._legacy_controls:
        return True
    context = getattr(window, "_navigation_context", "Главное меню")
    if target in GAME:
        return bool(window._session.generated_world) and (
            context in GAME
            or context == "Главное меню"
            or getattr(window, "_entering_adventure", False)
        )
    if target == "Главное меню" or target == context:
        return True
    if target in STANDALONE:
        return context == "Главное меню"
    if target in TECHNICAL:
        return context in {"Главное меню", "Настройки", "Разработчик"}
    return False


def visible_sections(window):
    current = window.tabs.tabText(window.tabs.currentIndex())
    if current in GAME and window._session.generated_world:
        return GAME | {"Главное меню"}
    return {current, "Главное меню"}
