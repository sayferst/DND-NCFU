"""Local optional prose and player-visible memory, independent of game calculations."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QPlainTextEdit, QPushButton

from rpg_vkr.domain.world import LOCATIONS
from rpg_vkr.narrative.context import build_frame, visible_changes
from rpg_vkr.narrative.ollama import OllamaClient


def install_narrator_panels(window):
    from rpg_vkr.ui.episode_panels import plain_label

    memory = window._episode_page("Память мира")
    window.memory_status = plain_label()
    memory.addWidget(window.memory_status)
    window.world_memory_view = QPlainTextEdit()
    window.world_memory_view.setReadOnly(True)
    window.world_memory_view.setFont(window.journal.font())
    window.world_memory_view.setAccessibleName("Известные игроку последствия событий")
    memory.addWidget(window.world_memory_view, 1)

    page = window._episode_page("Рассказчик")
    page.addWidget(
        plain_label(
            "Автономная игра работает всегда. Локальный ИИ может дополнить подтверждённые "
            "события художественным текстом. Предметы, мир и числа он пока не создаёт. "
            "Нужны отдельно установленные Ollama и локальная модель. Эта кнопка их не скачивает."
        )
    )
    window.enable_local_narrator = QCheckBox("Использовать локального ИИ-рассказчика")
    page.addWidget(window.enable_local_narrator)
    window.local_model = QComboBox()
    window.local_model.setAccessibleName("Установленная локальная модель")
    page.addWidget(window.local_model)
    window.find_models_button = QPushButton("Найти установленные модели")
    page.addWidget(window.find_models_button)
    window.auto_narration = QCheckBox("Дополнять новые игровые действия автоматически")
    window.auto_narration.setChecked(True)
    page.addWidget(window.auto_narration)
    window.narrate_button = QPushButton("Рассказать текущую сцену")
    page.addWidget(window.narrate_button)
    window.cancel_narration_button = QPushButton("Отменить ожидание")
    page.addWidget(window.cancel_narration_button)
    window.narrator_status = plain_label(
        "Выбран автономный рассказчик. Загрузок и запросов к ИИ нет."
    )
    page.addWidget(window.narrator_status)
    page.addWidget(plain_label("Факты сцены, доступные рассказчику:"))
    window.narrator_context = QPlainTextEdit()
    window.narrator_context.setReadOnly(True)
    window.narrator_context.setFont(window.journal.font())
    window.narrator_context.setAccessibleName("Доступный рассказчику контекст без секретов NPC")
    page.addWidget(window.narrator_context, 1)

    window.ollama = OllamaClient(window)
    window._narrating_session = None
    window._narrating_index = None
    window._narrator_frame = None
    window.find_models_button.clicked.connect(window.ollama.list_models)
    window.narrate_button.clicked.connect(lambda: request_narration(window))
    window.cancel_narration_button.clicked.connect(lambda: cancel_narration(window))
    window.enable_local_narrator.toggled.connect(lambda enabled: change_mode(window, enabled))
    window.local_model.currentIndexChanged.connect(lambda index: refresh_narrator_panels(window))
    window.ollama.models_ready.connect(lambda models: models_ready(window, models))
    window.ollama.narration_ready.connect(lambda note: accept_narration(window, note))
    window.ollama.failed.connect(lambda message: failed(window, message))
    window.ollama.busy_changed.connect(lambda busy: refresh_narrator_panels(window))
    refresh_narrator_panels(window)


def change_mode(window, enabled):
    if not enabled:
        cancel_narration(window)
    window.narrator_status.setText(
        "Локальный режим выбран. Найдите установленную модель; обычные действия уже доступны."
        if enabled
        else "Выбран автономный рассказчик. Сохранённые тексты ИИ остаются в истории."
    )
    refresh_narrator_panels(window)


def cancel_narration(window):
    window._narrating_session = None
    window._narrating_index = None
    window._narrator_frame = None
    window.ollama.cancel()
    window.narrator_status.setText(
        "Ожидание отменено. Игровые действия и броски сохранены в журнале."
    )
    refresh_narrator_panels(window)


def failed(window, message):
    window._narrating_session = None
    window._narrator_frame = None
    window.narrator_status.setText(message)
    window.statusBar().showMessage(message, 10000)
    refresh_narrator_panels(window)


def models_ready(window, models):
    previous = window.local_model.currentText()
    window.local_model.clear()
    window.local_model.addItems(list(models))
    index = window.local_model.findText(previous)
    if index >= 0:
        window.local_model.setCurrentIndex(index)
    window.narrator_status.setText(
        f"Локальных моделей найдено: {len(models)}. Выберите модель и запросите рассказ."
        if models
        else "Установленных локальных моделей нет. Облачные модели не предлагаются."
    )
    refresh_narrator_panels(window)


def request_narration(window):
    if (
        getattr(window, "_closing", False)
        or not window.enable_local_narrator.isChecked()
        or window.ollama.busy
        or not window.local_model.currentText()
        or any(n.turn_index == len(window._session.turns) for n in window._session.narrations)
    ):
        return
    window._narrator_frame = build_frame(window._session)
    window._narrating_session = window._session
    window._narrating_index = len(window._session.turns)
    window.narrator_status.setText(
        "Локальная модель пишет рассказ. Можно отменить ожидание или продолжить играть."
    )
    window.ollama.narrate(window._narrator_frame, window.local_model.currentText())


def accept_narration(window, note):
    if (
        window._narrating_session is not window._session
        or window._narrating_index != len(window._session.turns)
        or not window.enable_local_narrator.isChecked()
    ):
        return
    try:
        window._session.add_narration(note)
    except ValueError:
        failed(
            window,
            "Сцена уже изменилась или рассказ для неё сохранён. Устаревший ответ не добавлен.",
        )
        return
    window._narrating_session = None
    window._narrator_frame = None
    window._dirty = True
    window._render_journal()
    window._refresh_slots()
    window.narrator_status.setText("Рассказ добавлен. Сохраните сессию в ячейку для продолжения.")
    refresh_narrator_panels(window)


def after_action(window, turn):
    if (
        window.enable_local_narrator.isChecked()
        and window.auto_narration.isChecked()
        and (turn.combat or turn.speaker in {"Мир", "Рассказчик"})
        and not turn.text.startswith("Я пока не понимаю")
        and turn.action.casefold() != "помощь"
    ):
        session, index = window._session, len(window._session.turns)
        QTimer.singleShot(
            0,
            window,
            lambda: request_narration(window)
            if window._session is session and len(session.turns) == index
            else None,
        )


def refresh_narrator_panels(window):
    if not hasattr(window, "ollama"):
        return
    session = window._session
    if window._narrating_session is not None and (
        window._narrating_session is not session or window._narrating_index != len(session.turns)
    ):
        cancel_narration(window)
    enabled, busy = window.enable_local_narrator.isChecked(), window.ollama.busy
    window.find_models_button.setEnabled(not busy)
    window.local_model.setEnabled(enabled and not busy)
    window.auto_narration.setEnabled(enabled)
    window.narrate_button.setEnabled(
        enabled
        and not busy
        and bool(window.local_model.currentText())
        and not any(n.turn_index == len(session.turns) for n in session.narrations)
    )
    window.cancel_narration_button.setEnabled(busy)
    window.mode_label.setText(
        "Локальный ИИ · "
        + (window.local_model.currentText() or "модель не выбрана")
        + " · правила и автономный рассказ работают локально"
        if enabled
        else "Автономный режим · без нейросети и интернета"
    )
    frame = build_frame(session)
    context = (
        f"{frame.hero}\n{frame.location}; здоровье {frame.health}\n"
        f"Инвентарь: {frame.inventory}\n{frame.quest}\n\n{frame.scene}\n"
        + "\n".join(frame.visible_actors)
        + "\n\nПодтверждённый итог:\n"
        + frame.confirmed_result
        + "\n\nПоследние известные изменения:\n"
        + "\n".join(frame.memories)
    )
    if window.narrator_context.toPlainText() != context:
        window.narrator_context.setPlainText(context)
    rows = []
    for event in session.memory.events:
        changes = visible_changes(event)
        if changes:
            turn = session.turns[event.turn_index - 1]
            rows.append(
                f"Событие {event.turn_index} · {LOCATIONS[event.location]} · {turn.action}\n"
                + "\n".join(changes)
            )
    text = (
        "\n\n".join(rows[-100:]) or "Значимых изменений пока нет. Осмотр сам по себе не меняет мир."
    )
    if window.world_memory_view.toPlainText() != text:
        window.world_memory_view.setPlainText(text)
    window.memory_status.setText(
        f"Записано действий: {len(session.memory.events)}. Показаны последние 100 изменений. "
        + (
            f"Подробная память начинается с действия {session.memory.base_turn + 1}; "
            "прежняя история сохранена без переигрывания. "
            if session.memory.base_turn
            else ""
        )
        + "Память и тексты ИИ сохраняются вместе с игровой ячейкой."
    )
