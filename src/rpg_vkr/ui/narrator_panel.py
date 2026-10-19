"""Local optional prose and player-visible memory, independent of game calculations."""

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QPlainTextEdit, QPushButton

from rpg_vkr.commands import CHAT_TARGETS
from rpg_vkr.domain.combat import ACTORS, ANGER_COMMANDS, ATTACK_COMMANDS
from rpg_vkr.domain.world import LOCATIONS
from rpg_vkr.narrative.context import build_frame, recent_dialogue, visible_changes
from rpg_vkr.narrative.dialogue import dialogue_context, last_interlocutor
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.narrative.ollama import OllamaClient
from rpg_vkr.narrative.records import Narration
from rpg_vkr.narrative.routing import infer_meaning, meaning_command, simple_action
from rpg_vkr.narrative.speech import validate_binding


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
            "В локальном чате ИИ понимает обычную речь и отвечает художественным текстом. "
            "Действия проверяет движок; предметы, мир и числа модель пока не создаёт. "
            "Без модели доступны автономные команды и быстрые кнопки. "
            "Нужны отдельно установленные Ollama и локальная модель. Эта кнопка их не скачивает."
        )
    )
    window.enable_local_narrator = QCheckBox("Использовать локального ИИ-рассказчика")
    page.addWidget(window.enable_local_narrator)
    window.ai_chat = QCheckBox("Понимать свободный текст через ИИ и отвечать в чате")
    window.ai_chat.setChecked(True)
    page.addWidget(window.ai_chat)
    window.local_model = QComboBox()
    window.local_model.setAccessibleName("Установленная локальная модель")
    page.addWidget(window.local_model)
    window.find_models_button = QPushButton("Найти установленные модели")
    page.addWidget(window.find_models_button)
    window.auto_narration = QCheckBox("Рассказ после быстрых кнопок (чат отвечает всегда)")
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
    window.show_narrator_details = QCheckBox("Показать последний технический ответ ИИ")
    page.addWidget(window.show_narrator_details)
    window.narrator_details = QPlainTextEdit()
    window.narrator_details.setReadOnly(True)
    window.narrator_details.setMaximumHeight(170)
    window.narrator_details.setAccessibleName("Последний ответ модели; в файлы не записывается")
    window.narrator_details.setPlaceholderText(
        "Здесь появятся этап, причина отказа и ответ модели."
    )
    window.narrator_details.setVisible(False)
    window.show_narrator_details.toggled.connect(window.narrator_details.setVisible)
    page.addWidget(window.narrator_details)
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
    window._chat_text = None
    window._profile_intent = None
    window.find_models_button.clicked.connect(window.ollama.list_models)
    window.narrate_button.clicked.connect(lambda: request_narration(window))
    window.cancel_narration_button.clicked.connect(lambda: cancel_narration(window))
    window.enable_local_narrator.toggled.connect(lambda enabled: change_mode(window, enabled))
    window.ai_chat.toggled.connect(lambda enabled: None if enabled else cancel_narration(window))
    window.local_model.currentIndexChanged.connect(lambda index: refresh_narrator_panels(window))
    window.ollama.models_ready.connect(lambda models: models_ready(window, models))
    window.ollama.narration_ready.connect(lambda note: accept_narration(window, note))
    window.ollama.intent_ready.connect(lambda intent: accept_intent(window, intent))
    window.ollama.profile_ready.connect(lambda profile: accept_profile(window, profile))
    window.ollama.failed.connect(lambda message: failed(window, message))
    window.ollama.busy_changed.connect(lambda busy: refresh_narrator_panels(window))
    window.ollama.diagnostics_ready.connect(window.narrator_details.setPlainText)
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
    if window._chat_text and not window.action_input.text():
        window.action_input.setText(window._chat_text)
    window._chat_text = None
    window._profile_intent = None
    window._narrating_session = None
    window._narrating_index = None
    window._narrator_frame = None
    window.ollama.cancel()
    window._render_journal()
    window.narrator_status.setText(
        "Ожидание отменено. Новое намерение не выполняется; уже выполненные действия сохранены."
    )
    refresh_narrator_panels(window)


def failed(window, message):
    if (
        window._chat_text
        and window._profile_intent is None
        and window._narrating_session is window._session
        and window._narrating_index == len(window._session.turns)
        and message.startswith("Распознавание сообщения:")
    ):
        fallback = simple_action(window._chat_text)
        if fallback:
            accept_intent(window, fallback)
            return
    if window._chat_text and not window.action_input.text():
        window.action_input.setText(window._chat_text)
    window._chat_text = None
    window._profile_intent = None
    window._narrating_session = None
    window._narrator_frame = None
    window._render_journal()
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
    window._render_journal()
    turn = window._session.turns[-1] if window._session.turns else None
    actor = ""
    if turn and turn.intent in CHAT_TARGETS:
        state = window._session.combat.actor(CHAT_TARGETS[turn.intent])
        if state.hp > 0 and state.disposition != "hostile" and turn.actor_id == state.id:
            actor = ACTORS[state.id][0]
    window.ollama.narrate(
        window._narrator_frame,
        window.local_model.currentText(),
        player_message=turn.action if turn and turn.intent else "",
        dialogue_actor=actor,
        history=recent_dialogue(window._session),
        clarify=bool(turn and turn.intent == "уточнить намерение"),
        dialogue=dialogue_context(window._session),
        campaign=campaign_context(
            window._session, turn.meaning.target if turn and turn.meaning else actor
        ),
    )


def request_chat(window, text):
    if not window.enable_local_narrator.isChecked() or not window.ai_chat.isChecked():
        return False
    if not window.local_model.currentText():
        failed(window, "Для свободного чата найдите и выберите локальную модель в «Рассказчик».")
        return True
    cancel_narration(window)
    window._chat_text = text
    window._narrating_session = window._session
    window._narrating_index = len(window._session.turns)
    window.action_input.clear()
    window.narrator_status.setText("ИИ понимает ваше сообщение. Мир пока не изменён.")
    window.statusBar().showMessage("ИИ понимает сообщение…")
    window.ollama.interpret(
        build_frame(window._session),
        window.local_model.currentText(),
        text,
        history=recent_dialogue(window._session),
        campaign=campaign_context(window._session, last_interlocutor(window._session)),
        conversation={"interlocutor_id": last_interlocutor(window._session)},
    )
    return True


def accept_intent(window, intent, profile=None):
    if (
        window._chat_text is None
        or window._narrating_session is not window._session
        or window._narrating_index != len(window._session.turns)
        or not window.enable_local_narrator.isChecked()
    ):
        return
    text = window._chat_text
    local = simple_action(text)
    if local and (intent.kind != "action" or intent.command != local.command):
        from dataclasses import replace

        intent = replace(local, source="local-correction")
    meaning = infer_meaning(window._session, text, intent)
    command = intent.command
    if intent.kind == "dialogue":
        command = next(key for key, target in CHAT_TARGETS.items() if target == intent.target)
    elif intent.kind == "clarify":
        command = "уточнить намерение"
    if meaning:
        command = meaning_command(meaning)
    target = ATTACK_COMMANDS.get(command) or ANGER_COMMANDS.get(command)
    binding_error = validate_binding(
        text,
        command,
        location=window._session.world.location,
        active_target=window._session.combat.active,
        interlocutor=last_interlocutor(window._session),
    )
    if binding_error:
        target = None  # Session records a clarification rather than proposing this attack.
    if (
        target
        and window._session.combat.actor(target).disposition == "neutral"
        and ACTORS[target][1] == window._session.world.location
    ):
        if not window._confirm(
            f"ИИ понял сообщение как «{command}». Это сделает персонажа враждебным. Продолжить?"
        ):
            cancel_narration(window)
            window.action_input.setText(text)
            window.narrator_status.setText("Действие отменено. Мир не изменён.")
            return
    if (
        profile is None
        and meaning
        and meaning.target
        and not binding_error
        and meaning.speech_act == "question"
        and meaning.topic in {"appearance", "background", "other"}
        and ACTORS[meaning.target][1] == window._session.world.location
        and not window._session.campaign.profile(meaning.target)
    ):
        window._profile_intent = intent
        window.narrator_status.setText("Мастер придумывает и проверяет детали персонажа…")
        window.ollama.create_profile(
            build_frame(window._session),
            window.local_model.currentText(),
            meaning.target,
            campaign={"genre": "сельское приключенческое фэнтези"},
        )
        return
    window._chat_text = None
    window._profile_intent = None
    window._narrating_session = None
    try:
        window._session.submit(
            text, intent=command, meaning=meaning, profile=profile, intent_source=intent.source
        )
    except ValueError as error:
        window.action_input.setText(text)
        failed(window, str(error))
        return
    window.action_input.remember(text)
    window._dirty = True
    window._refresh_character()
    window._render_journal()
    if not meaning and intent.kind == "clarify" and intent.question:
        frame = build_frame(window._session)
        window._narrating_session = window._session
        window._narrating_index = len(window._session.turns)
        accept_narration(
            window,
            Narration(
                len(window._session.turns),
                window.local_model.currentText(),
                intent.question,
                frame.fingerprint,
            ),
        )
    else:
        request_narration(window)


def accept_profile(window, profile):
    intent = window._profile_intent
    if intent is not None:
        accept_intent(window, intent, profile)


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
        and (turn.combat or turn.speaker in {"Мир", "Рассказчик"} or turn.actor_id is not None)
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
    window.ai_chat.setEnabled(enabled)
    window.narrate_button.setEnabled(
        enabled
        and not busy
        and bool(window.local_model.currentText())
        and not any(n.turn_index == len(session.turns) for n in session.narrations)
    )
    window.cancel_narration_button.setEnabled(busy)
    window.mode_label.setText("Мастер" if enabled else "Мастер · автономный режим")
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
    if session.campaign.npc_profiles:
        text += "\n\nЗапомненные описания жителей:\n" + "\n\n".join(
            f"{ACTORS[profile.actor_id][0]}: {profile.appearance} {profile.ancestry}"
            for profile in session.campaign.npc_profiles
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
