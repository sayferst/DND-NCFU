"""Local optional prose and player-visible memory, independent of game calculations."""

import sqlite3

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QPlainTextEdit, QPushButton

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
    window.export_campaign_button = QPushButton("Экспорт всей сессии в SQLite…")
    window.export_campaign_button.clicked.connect(lambda: export_campaign(window))
    memory.addWidget(window.export_campaign_button)
    window.import_campaign_button = QPushButton("Открыть сессию из SQLite…")
    window.import_campaign_button.clicked.connect(lambda: import_campaign(window))
    memory.addWidget(window.import_campaign_button)

    page = window._episode_page("Рассказчик" if window._legacy_controls else "Мастер")
    if not window._legacy_controls:
        window.artist_page = window._episode_page("Художник")
    page.addWidget(
        plain_label(
            "ИИ-мастер понимает обычную речь и отвечает художественным текстом. "
            "Мастер создаёт детали и реакции NPC; механику и изменения ресурсов проверяет движок. "
            "Для игры нужен включённый облачный мастер. "
            "Без подключения доступны сохранения, дневник и просмотр знаний."
        )
    )
    window.enable_local_narrator = QCheckBox("Включить ИИ-мастера")
    page.addWidget(window.enable_local_narrator)
    window.ai_chat = QCheckBox("Понимать свободный текст через ИИ и отвечать в чате")
    window.ai_chat.setChecked(True)
    page.addWidget(window.ai_chat)
    window.world_agent = QCheckBox("Применять действия ИИ через проверяемый план мира")
    window.world_agent.setChecked(not window._legacy_controls)
    page.addWidget(window.world_agent)
    window.world_agent.toggled.connect(
        lambda _: cancel_if_busy(window) if hasattr(window, "ollama") else None
    )
    window.prompt_notice = plain_label(
        "Инструкция мастера: prompts/master_system_prompt.txt. "
        "Личная версия: prompts/master_system_prompt.local.txt — "
        "применяется со следующего запроса. "
        "Пожелания к миру задаются отдельно при создании героя."
    )
    page.addWidget(window.prompt_notice)
    window.ai_provider = QComboBox()
    if window._legacy_controls:
        window.ai_provider.addItem("Локально: Ollama · без оплаты API", "local")
    window.ai_provider.addItem("Облако: OpenAI API · отдельный доступ", "openai")
    window.ai_provider.addItem("Облако: OpenRouter API · условия провайдера", "openrouter")
    window.ai_provider.addItem("Облако: RouterAI · тарифы в рублях", "routerai")
    page.addWidget(window.ai_provider)
    window.cloud_model = QLineEdit()
    window.cloud_model.setPlaceholderText("Идентификатор модели API (указывается у провайдера)")
    page.addWidget(window.cloud_model)
    window.routerai_catalog_button = QPushButton("Загрузить модели и цены RouterAI")
    page.addWidget(window.routerai_catalog_button)
    window.routerai_model_list = QComboBox()
    window.routerai_model_list.addItem("Выберите модель из каталога", "")
    page.addWidget(window.routerai_model_list)
    window.routerai_price = plain_label("Цены не проверены. Загрузите текущий каталог RouterAI.")
    page.addWidget(window.routerai_price)
    window.cloud_free_only = QCheckBox("OpenRouter: только бесплатные модели, без платной замены")
    window.cloud_free_only.setChecked(True)
    page.addWidget(window.cloud_free_only)
    window.cloud_key = QLineEdit()
    window.cloud_key.setEchoMode(QLineEdit.EchoMode.Password)
    window.cloud_key.setPlaceholderText("API-ключ или переменная RPG_VKR_LLM_API_KEY")
    page.addWidget(window.cloud_key)
    window.cloud_allowed = QCheckBox("Разрешаю отправлять сцену в API по условиям моего провайдера")
    page.addWidget(window.cloud_allowed)
    window.cloud_notice = plain_label(
        "Подписка ChatGPT Plus не включает API. Возможны отдельные расходы/лимиты. "
        "Ключ хранится только в памяти; запросы идут после вашего действия."
    )
    page.addWidget(window.cloud_notice)
    window.ai_provider.currentIndexChanged.connect(lambda _: provider_changed(window))
    window.director_mode = QCheckBox("Мастер: развивать сцену и запоминать новые детали")
    window.director_mode.setChecked(True)
    window.director_mode.toggled.connect(lambda enabled: cancel_narration(window))
    page.addWidget(window.director_mode)
    window.director_mode.setVisible(window._legacy_controls)
    window.local_model = QComboBox()
    window.local_model.setAccessibleName("Установленная локальная модель")
    page.addWidget(window.local_model)
    window.find_models_button = QPushButton("Найти установленные модели")
    page.addWidget(window.find_models_button)
    window.auto_narration = QCheckBox("Рассказ после быстрых кнопок (чат отвечает всегда)")
    window.auto_narration.setChecked(True)
    page.addWidget(window.auto_narration)
    window.auto_narration.setVisible(window._legacy_controls)
    window.narrate_button = QPushButton("Рассказать текущую сцену")
    page.addWidget(window.narrate_button)
    window.narrate_button.setVisible(window._legacy_controls)
    window.cancel_narration_button = QPushButton("Отменить ожидание")
    page.addWidget(window.cancel_narration_button)
    window.narrator_status = plain_label(
        "Мастер выключен. Настройте облачное подключение для игры."
    )
    page.addWidget(window.narrator_status)
    window.narrator_metrics = plain_label("Метрики генерации: запросов пока нет.")
    page.addWidget(window.narrator_metrics)
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
    from rpg_vkr.narrative.routerai import RouterAIClient

    window.routerai_catalog = RouterAIClient(window)
    window.routerai_key_client = RouterAIClient(window)
    window._routerai_quotes = {}
    window.routerai_catalog_button.clicked.connect(lambda: load_routerai_models(window))
    window.routerai_model_list.activated.connect(lambda index: select_routerai_model(window, index))
    window.routerai_catalog.catalog_ready.connect(
        lambda quotes: routerai_models_ready(window, quotes)
    )
    window.routerai_catalog.failed.connect(lambda message: catalog_failed(window, message))
    window.routerai_catalog.busy_changed.connect(lambda _: refresh_narrator_panels(window))
    window.routerai_key_client.busy_changed.connect(lambda _: refresh_narrator_panels(window))
    window._narrating_session = None
    window._narrating_index = None
    window._narrator_frame = None
    window._chat_text = None
    window._profile_intent = None
    window.find_models_button.clicked.connect(lambda: find_models(window))
    window.narrate_button.clicked.connect(lambda: request_narration(window))
    window.cancel_narration_button.clicked.connect(lambda: cancel_narration(window))
    window.enable_local_narrator.toggled.connect(lambda enabled: change_mode(window, enabled))
    window.ai_chat.toggled.connect(lambda enabled: None if enabled else cancel_narration(window))
    window.local_model.currentIndexChanged.connect(lambda index: refresh_narrator_panels(window))
    window.ollama.models_ready.connect(lambda models: models_ready(window, models))
    window.ollama.narration_ready.connect(lambda note: accept_narration(window, note))
    window.ollama.intent_ready.connect(lambda intent: accept_intent(window, intent))
    window.ollama.proposal_ready.connect(lambda proposal: accept_proposal(window, proposal))
    window.ollama.profile_ready.connect(lambda profile: accept_profile(window, profile))
    window.ollama.challenge_ready.connect(
        lambda category: accept_challenge_suggestion(window, category)
    )
    window.ollama.world_plan_ready.connect(lambda result: accept_world_plan(window, result))
    window.ollama.progress.connect(window.narrator_status.setText)
    window.ollama.failed.connect(lambda message: failed(window, message))
    window.ollama.busy_changed.connect(lambda busy: refresh_narrator_panels(window))
    window.ollama.diagnostics_ready.connect(window.narrator_details.setPlainText)
    window.ollama.event_ready.connect(lambda event: record_model_event(window, event))
    window.cloud_key.textEdited.connect(lambda _: cancel_if_busy(window))
    window.cloud_model.textEdited.connect(lambda _: cancel_if_busy(window))
    window.cloud_model.textChanged.connect(lambda _: refresh_model_price(window))
    window.cloud_allowed.toggled.connect(
        lambda allowed: None if allowed else cancel_if_busy(window)
    )
    if not window._legacy_controls:
        from rpg_vkr.ui.connection_panel import install_connection_layout

        install_connection_layout(window, page)
    provider_changed(window)
    refresh_narrator_panels(window)


def provider_changed(window):
    if window.ollama.busy or window._chat_text is not None or window._narrating_session is not None:
        cancel_narration(window)
    window.routerai_catalog.cancel()
    window.routerai_key_client.cancel()
    provider = window.ai_provider.currentData()
    window.world_agent.setVisible(provider == "routerai" or not window._legacy_controls)
    previous = getattr(window, "_previous_ai_provider", None)
    if previous is not None and previous != provider:
        window.cloud_key.clear()
        window.cloud_model.clear()
        window.cloud_allowed.setChecked(False)
        if hasattr(window, "show_api_key"):
            window.show_api_key.setChecked(False)
    window._previous_ai_provider = provider
    cloud = window.ai_provider.currentData() != "local"
    for widget in (window.cloud_model, window.cloud_key, window.cloud_allowed, window.cloud_notice):
        widget.setVisible(cloud)
    window.cloud_free_only.setVisible(window.ai_provider.currentData() == "openrouter")
    for widget in (
        window.routerai_catalog_button,
        window.routerai_model_list,
        window.routerai_price,
    ):
        widget.setVisible(provider == "routerai")
    window.cloud_key.setPlaceholderText(
        "Ключ RouterAI или переменная RPG_VKR_ROUTERAI_API_KEY"
        if provider == "routerai"
        else "API-ключ или переменная RPG_VKR_LLM_API_KEY"
    )
    if provider == "routerai":
        window.cloud_notice.setText(
            "RouterAI оплачивается отдельно. Используйте обычный API-ключ с месячным лимитом "
            "не более 2000 ₽; перед каждой генерацией игра проверит лимит. "
            "Ключи и баланс приложение не изменяет."
        )
        if not window.cloud_model.text().strip():
            window.cloud_model.setText("deepseek/deepseek-v4-flash-latest")
    else:
        window.cloud_notice.setText(
            "Подписка ChatGPT Plus не включает API. Возможны отдельные расходы/лимиты. "
            "Ключ хранится только в памяти; запросы идут после вашего действия."
        )
    if window.ai_provider.currentData() == "openrouter" and not window.cloud_model.text().strip():
        window.cloud_model.setText("openrouter/free")
    window.director_mode.setEnabled(not cloud)
    if cloud:
        window._local_models = (
            tuple(window.ollama.models)
            if not window.ollama.cloud
            else getattr(window, "_local_models", ())
        )
        window.director_mode.setChecked(True)
        window.find_models_button.setText("Применить настройки облачного API")
        window.local_model.clear()
        window.local_model.setVisible(window._legacy_controls)
        window.ollama.use_local()
    else:
        window.local_model.show()
        window.ollama.use_local()
        window.find_models_button.setText("Найти установленные модели")
        window.local_model.clear()
        window.local_model.addItems(list(getattr(window, "_local_models", ())))
        window.ollama.models = tuple(getattr(window, "_local_models", ()))

    from rpg_vkr.ui.connection_panel import refresh_connection_layout

    refresh_connection_layout(window)


def cancel_if_busy(window):
    if window.ollama.busy:
        cancel_narration(window)


def load_routerai_models(window):
    if window.ai_provider.currentData() != "routerai":
        return
    if hasattr(window, "catalog_status"):
        window.catalog_status.setText("Загрузка каталога RouterAI… API-ключ не передаётся.")
    window.routerai_catalog.list_models()


def catalog_failed(window, message):
    if window.ai_provider.currentData() != "routerai":
        return
    if hasattr(window, "catalog_status"):
        window.catalog_status.setText(message + " Можно оставить ID модели вручную.")
    if not window.ollama.busy:
        window.narrator_status.setText(message)


def refresh_model_price(window):
    quote = window._routerai_quotes.get(window.cloud_model.text().strip())
    window.routerai_price.setText(
        quote.label if quote else "Цена не подтверждена. Можно обновить каталог RouterAI."
    )


def routerai_models_ready(window, quotes):
    if window.ai_provider.currentData() != "routerai" or getattr(window, "_closing", False):
        return
    from rpg_vkr.ui.connection_panel import filter_models

    window._routerai_quotes = {quote.id: quote for quote in quotes}
    filter_models(window)
    current = window.cloud_model.text().strip()
    if current in window._routerai_quotes:
        window.routerai_price.setText(window._routerai_quotes[current].label)
    else:
        window.routerai_price.setText("ID введён вручную; цена и наличие модели не подтверждены.")
    if hasattr(window, "catalog_status"):
        unknown = sum(q.prompt_rub is None for q in quotes)
        window.catalog_status.setText(
            f"Каталог загружен: {len(quotes)} текстовых моделей; "
            f"без подтверждённой цены: {unknown}. "
            "Это не проверка ключа. Выберите модель и подключите мастера."
        )
    if not window.ollama.busy:
        window.narrator_status.setText("Каталог получен. Платных запросов не было.")


def select_routerai_model(window, index):
    model = window.routerai_model_list.itemData(index)
    quote = window._routerai_quotes.get(model)
    if quote:
        cancel_if_busy(window)
        window.cloud_model.setText(quote.id)
        window.routerai_price.setText(quote.label)


def prepare_model(window):
    if window.ai_provider.currentData() == "local":
        window.ollama.use_local()
        return bool(window.local_model.currentText())
    import os

    from rpg_vkr.narrative.cloud import CloudProfile

    if not window.cloud_allowed.isChecked():
        failed(
            window,
            "Для облака разрешите отправку сцены в API. Реплика не отправлена.",
        )
        return False
    try:
        provider = window.ai_provider.currentData()
        quote = (
            window._routerai_quotes.get(window.cloud_model.text().strip())
            if provider == "routerai"
            else None
        )
        profile = CloudProfile(
            provider,
            window.cloud_model.text().strip(),
            window.cloud_key.text().strip()
            or os.environ.get(
                "RPG_VKR_ROUTERAI_API_KEY" if provider == "routerai" else "RPG_VKR_LLM_API_KEY", ""
            ),
            free_only=window.ai_provider.currentData() == "openrouter"
            and window.cloud_free_only.isChecked(),
            supported_parameters=quote.supported_parameters if quote else (),
        )
    except ValueError as error:
        failed(window, str(error))
        return False
    window.ollama.configure_cloud(profile)
    window.local_model.clear()
    window.local_model.addItem(profile.model)
    return True


def find_models(window):
    if window.ai_provider.currentData() == "local":
        window.ollama.list_models()
    elif not window._legacy_controls:
        from rpg_vkr.ui.flash_settings import connect_selected

        connect_selected(window)
    elif prepare_model(window):
        window.narrator_status.setText(
            "Профиль API выбран. Запрос к модели будет отправлен с вашим сообщением."
        )


def change_mode(window, enabled):
    if not enabled:
        cancel_narration(window)
    if not window._legacy_controls:
        window.narrator_status.setText(
            "Облачный мастер выбран. Проверьте модель, ключ и разрешение отправки сцены."
            if enabled
            else "Мастер выключен. Для новых действий включите облачное подключение."
        )
        refresh_narrator_panels(window)
        return
    window.narrator_status.setText(
        "Локальный режим выбран. Найдите установленную модель; обычные действия уже доступны."
        if enabled
        else "Мастер выключен. История сохранена; для новых действий включите облако."
    )
    refresh_narrator_panels(window)


def cancel_narration(window):
    if window.routerai_catalog.busy and hasattr(window, "catalog_status"):
        window.catalog_status.setText("Загрузка каталога отменена. Предыдущий список сохранён.")
    window.routerai_catalog.cancel()
    window.routerai_key_client.cancel()
    if hasattr(window, "_flash_pending") and window._flash_pending:
        from rpg_vkr.ui.flash_settings import cancel_connection

        cancel_connection(window)
    if getattr(window, "_generating_session", None) is window._session:
        window.ollama.cancel()
        from rpg_vkr.ui.adventure_panel import generation_failed

        generation_failed(window, "Ожидание отменено.")
        return
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
    if getattr(window, "_generating_session", None) is window._session:
        from rpg_vkr.ui.adventure_panel import generation_failed

        generation_failed(window, message)
        return
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
    failure = getattr(window.ollama, "last_failure", None) or {}
    if (
        window._chat_text
        and (
            failure.get("stage") == "world_plan"
            or message.startswith(
                ("План не выполнен:", "Попытка не выполнена:", "Сделка не выполнена:")
            )
        )
        and failure.get("code") not in {"network", "access_or_budget", "request_budget"}
        and not getattr(window, "_recovering_plan", False)
    ):
        window._recovering_plan = True
        window._story_obstacle = (
            "Изменение состояния не подтверждено: "
            + failure.get("reason", message)
            + ". Ответь на намерение; объясни препятствие без вымышленного успеха."
        )
        continue_story(window, window._chat_text)
        return
    if window._chat_text and not window.action_input.text():
        window.action_input.setText(window._chat_text)
    window._chat_text = None
    window._profile_intent = None
    window._narrating_session = None
    window._narrator_frame = None
    window._render_journal()
    window._model_turn_open = False
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
        else "Локальных моделей нет. Облачный API настраивается отдельно."
    )
    refresh_narrator_panels(window)


def request_narration(window):
    if not getattr(window, "_model_turn_open", False):
        window.ollama.begin_turn()
        window._telemetry_session = window._session
        window._model_turn_open = True
    if window.ai_provider.currentData() != "local" and not prepare_model(window):
        return
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
        player_message=turn.action
        if turn
        and (turn.intent or turn.challenge or turn.interaction or turn.catalog or turn.trade)
        else "",
        dialogue_actor=actor,
        history=recent_dialogue(window._session),
        clarify=bool(turn and turn.intent == "уточнить намерение"),
        dialogue=dialogue_context(window._session),
        plain=window.director_mode.isChecked(),
        campaign=campaign_context(
            window._session, turn.meaning.target if turn and turn.meaning else actor
        ),
    )


def request_chat(window, text):
    if not window.enable_local_narrator.isChecked() or not window.ai_chat.isChecked():
        return False
    if not prepare_model(window):
        if window.ai_provider.currentData() != "local":
            return True
        failed(window, "Выберите модель и настройте подключение в панели ИИ-мастера.")
        return True
    cancel_narration(window)
    window.ollama.begin_turn()
    window._telemetry_session = window._session
    window._model_base_turn = len(window._session.turns)
    window._model_turn_open = True
    window._pending_memories = []
    window._chat_target_id = ""
    window._story_obstacle = ""
    window._recovering_plan = False
    window._chat_text = text
    window._narrating_session = window._session
    window._narrating_index = len(window._session.turns)
    window.action_input.clear()
    window.narrator_status.setText("ИИ понимает ваше сообщение. Мир пока не изменён.")
    window.statusBar().showMessage("ИИ понимает сообщение…")
    if world_agent_enabled(window):
        window._catalog_reads = 0
        window.ollama.plan_world(
            build_frame(window._session),
            window.local_model.currentText(),
            text,
            catalog_context(window, text),
            window._session.campaign.world_brief,
        )
        return True
    if window.director_mode.isChecked():
        from rpg_vkr.domain.director import Proposal
        from rpg_vkr.narrative.intent import Interpretation
        from rpg_vkr.narrative.story import master_question, mechanical_request
        from rpg_vkr.narrative.turn_brief import turn_brief
        from rpg_vkr.storage.knowledge import retrieve

        frame = build_frame(window._session)
        memory = retrieve(window._session, text)
        campaign = campaign_context(window._session, last_interlocutor(window._session))
        brief = turn_brief(
            frame, text, memory=memory, campaign=campaign, master=master_question(text)
        )
        command = mechanical_request(text)
        if not command and brief.get("clarification"):
            accept_proposal(
                window, Proposal("", "", brief["clarification"], ()), source="local-clarification"
            )
        elif command:
            accept_intent(
                window, Interpretation("action", command, "", "", source="local-fallback")
            )
        elif (
            window.ollama.cloud
            and window.local_model.currentText().startswith("deepseek/")
            and brief.get("mode") == "scene"
            and not simple_action(text)
        ):
            from rpg_vkr.domain.challenge import needs_model_review

            if needs_model_review(text):
                window.ollama.suggest_challenge(frame, window.local_model.currentText(), text)
            else:
                continue_story(window, text)
        else:
            continue_story(window, text)
        return True
    window.ollama.interpret(
        build_frame(window._session),
        window.local_model.currentText(),
        text,
        history=recent_dialogue(window._session),
        campaign=campaign_context(window._session, last_interlocutor(window._session)),
        conversation={"interlocutor_id": last_interlocutor(window._session)},
    )
    return True


def continue_story(window, text):
    from rpg_vkr.storage.knowledge import retrieve

    campaign = campaign_context(window._session, last_interlocutor(window._session))
    campaign["requested_target"] = getattr(window, "_chat_target_id", "")
    campaign["obstacle"] = getattr(window, "_story_obstacle", "")
    campaign["proposed_memories"] = [
        n for n in getattr(window, "_pending_memories", []) if not n["private"]
    ]
    window.ollama.develop(
        build_frame(window._session),
        window.local_model.currentText(),
        text,
        memory=retrieve(window._session, text),
        campaign=campaign,
        history=[
            {
                "player": t.action,
                "result": t.text[:1500],
                "source": t.scene.version if t.scene else "rules",
                "actor_id": t.actor_id or "",
            }
            for t in window._session.turns[-3:]
        ],
    )


def accept_inline_reply(window, text, reply):
    """The planner may also write a conversation; validate it without another POST."""
    from rpg_vkr.narrative.story import story_context, story_proposal
    from rpg_vkr.storage.knowledge import retrieve

    frame = build_frame(window._session)
    campaign = campaign_context(window._session, last_interlocutor(window._session))
    campaign["requested_target"] = getattr(window, "_chat_target_id", "")
    campaign["obstacle"] = getattr(window, "_story_obstacle", "")
    context = story_context(
        frame,
        window.local_model.currentText(),
        text,
        campaign=campaign,
        memory=retrieve(window._session, text),
    )
    try:
        proposal = story_proposal(
            {"message": {"role": "assistant", "content": reply}}, frame, text, context=context
        )
    except (ValueError, TypeError) as error:
        window.ollama.record_validation(False, str(error))
        window._story_obstacle = "Предыдущий текст противоречил фактам: " + str(error)
        continue_story(window, text)
        return
    window.ollama.record_validation(True)
    accept_proposal(window, proposal)


def accept_challenge_suggestion(window, category):
    if (
        window._chat_text is None
        or window._narrating_session is not window._session
        or window._narrating_index != len(window._session.turns)
        or not window.enable_local_narrator.isChecked()
    ):
        return
    text = window._chat_text
    if category == "none":
        continue_story(window, text)
    else:
        request_challenge(window, text, suggested_kind=category)


def request_local_actions(window, text):
    """Explicit mechanics work even when the selected model/key is unavailable."""
    import re

    from rpg_vkr.commands import normalise_action
    from rpg_vkr.narrative.actions import action_plan

    value = normalise_action(text)
    if re.fullmatch(
        r"(?:(?:хочу\s+)?(?:осмотреть|посмотреть|проверить|покажи|показать)\s+)?(?:свой\s+|мой\s+)?инвентар[ьe]",
        value,
    ):
        cancel_narration(window)
        window._session.submit(text, intent="инвентарь", intent_source="local-fallback")
        window.action_input.remember(text)
        window.action_input.clear()
        window._dirty = True
        window._refresh_character()
        window._render_journal()
        window.narrator_status.setText("Инвентарь показан по сохранённому состоянию мира.")
        return True
    plan = action_plan(window._session, text, allow_interactions=world_agent_enabled(window))
    if plan is None:
        return request_challenge(window, text)
    cancel_narration(window)
    if plan.clarification:
        window.narrator_status.setText(plan.clarification)
        window.statusBar().showMessage(plan.clarification)
        return True
    if (
        plan.target
        and window._session.combat.actor(plan.target).disposition == "neutral"
        and window._session.combat.actor(plan.target).hp > 0
    ):
        if not window._confirm(
            "Вы намерены напасть на нейтрального персонажа. Это начнёт схватку. Продолжить?"
        ):
            return True
    try:
        window._session.submit_actions(text)
    except ValueError as error:
        window.narrator_status.setText(str(error))
        return True
    window.action_input.remember(text)
    window.action_input.clear()
    window._dirty = True
    window._refresh_character()
    window._render_journal()
    window.narrator_status.setText("Действие рассчитано и сохранено в сессии.")
    if window.enable_local_narrator.isChecked() and window.ai_chat.isChecked():
        request_narration(window)
    return True


def world_agent_enabled(window):
    return (
        window.world_agent.isChecked()
        and window.enable_local_narrator.isChecked()
        and window.ai_chat.isChecked()
        and (window.ai_provider.currentData() == "routerai" or not window._legacy_controls)
    )


def catalog_context(window, text):
    from rpg_vkr.domain.catalog import CATEGORIES
    from rpg_vkr.storage.catalog import CatalogIndex

    state = window._session.interaction_state().context()
    target = getattr(window, "_context_target_id", "")
    state["selected_target"] = target if window._session.actor_is_here(target) else ""
    if window._campaign_repository:
        try:
            state["persistent_memory"] = window._campaign_repository.recall(
                window._session, text, private=True
            )
        except (OSError, ValueError, sqlite3.Error):
            state["persistent_memory"] = {}
    from rpg_vkr.domain.resources import NAMES, POOL_IDS, physical

    state["resource_pools"] = (
        []
        if physical(window._session.interaction_state())
        else [
            {"id": id, "name": NAMES[field], "quantity": getattr(window._session.world, field)}
            for field, id in POOL_IDS.items()
            if getattr(window._session.world, field)
        ]
    )
    if window._session.catalog:
        state["object_count"] = len(state["objects"])
        state["objects"] = sorted(state["objects"], key=lambda o: not o["available_here"])[:40]
        state["actors_here"] = state["actors_here"][:20]
    state["recent_actions"] = [t.action[:300] for t in window._session.turns[-4:]]
    state["conversation_memory"] = campaign_context(window._session).get("actors", [])
    index = CatalogIndex(window._session)
    try:
        state["catalog_records"] = index.relevant(text)
        state["category_codes"] = CATEGORIES
        return state
    finally:
        index.close()


def accept_world_plan(window, result):
    from rpg_vkr.domain.interactions import (
        PlanConfirmationRequired,
        apply_plan,
        bind_plan,
        requests_physical_change,
    )

    if (
        window._chat_text is None
        or window._narrating_session is not window._session
        or window._narrating_index != len(window._session.turns)
        or not world_agent_enabled(window)
    ):
        return
    from rpg_vkr.domain.catalog import (
        Registration,
        register,
        seed_catalog,
        validate_plan_properties,
    )

    plan, category, definitions, entities, reason, queries, attempt, memories, trade = result[:9]
    hints = result[9] if len(result) > 9 else {}
    window._chat_target_id = hints.get("dialogue_target") or ""
    window._story_obstacle = hints.get("obstacle") or ""
    window._pending_memories = memories
    text = window._chat_text
    if trade:
        import re

        from rpg_vkr.domain.interactions import nonexecuting
        from rpg_vkr.domain.trade import transact
        from rpg_vkr.narrative.speech import unquoted

        if nonexecuting(text, r"(?:куп|прод|меня|отда)") or re.search(r"\bесли\b", unquoted(text)):
            failed(window, "Вопрос, отрицание и цитата не выполняют сделку.")
            return
        try:
            _, _, quote = transact(
                window._session.catalog,
                window._session.interaction_state(),
                window._session.world,
                trade["merchant_id"],
                trade["item_id"],
                trade["operation"],
                trade["quantity"],
                len(window._session.turns) + 1,
                window.ollama.response_model or window.local_model.currentText(),
                window._session.catalog_aliases,
            )
            memory_update = (
                window._session.checked_memories(
                    memories, quote.source, scene=quote.after, turn=len(window._session.turns) + 1
                )
                if memories
                else window._session.chronicle
            )
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            failed(window, "Сделка не выполнена: " + str(error))
            return
        if not window._confirm(quote.summary + "\nВыполнить эту сделку?"):
            cancel_narration(window)
            return
        cancel_narration(window)
        window._session.submit_trade(
            text,
            trade["merchant_id"],
            trade["item_id"],
            trade["operation"],
            trade["quantity"],
            quote.source,
        )
        window._session.chronicle = memory_update
        window.action_input.remember(text)
        window.action_input.clear()
        window._dirty = True
        window._refresh_character()
        window._render_journal()
        request_narration(window)
        return
    if attempt:
        from rpg_vkr.domain.catalog_actions import resolve_attempt
        from rpg_vkr.domain.character import ABILITY_NAMES
        from rpg_vkr.domain.dice import D20Roll

        try:
            memory_update = (
                window._session.checked_memories(
                    memories,
                    window.ollama.response_model or window.local_model.currentText(),
                    turn=len(window._session.turns) + 1,
                )
                if memories
                else window._session.chronicle
            )
            _, _, preview_record = resolve_attempt(
                window._session.catalog or seed_catalog(),
                window._session.interaction_state(),
                window._session.world,
                window._session.character,
                attempt["target_id"],
                attempt["operation"],
                attempt["lethal"],
                D20Roll(1, 10),
                attempt["reason"],
                window.ollama.response_model or window.local_model.currentText(),
                len(window._session.turns),
                window._session.legacy_catalog_actor(attempt["target_id"]),
                preview=True,
            )
        except (ValueError, TypeError, KeyError) as error:
            failed(window, "Попытка не выполнена: " + str(error))
            return
        operation_name = {
            "attack": "Нападение",
            "heal": "Перевязка",
            "help": "Помощь",
            "hinder": "Попытка помешать",
            "insult": "Обидное обращение",
        }[attempt["operation"]]
        target_name = next(
            (
                a.name
                for a in window._session.interaction_state().actor_refs
                if a.id == attempt["target_id"]
            ),
            attempt["target_id"],
        )
        if not window._confirm(
            operation_name
            + ": "
            + target_name
            + ("; смертельное намерение" if attempt["lethal"] else "")
            + "\n"
            + attempt["reason"]
            + "\n"
            + ABILITY_NAMES[preview_record.check.ability]
            + f", сложность {preview_record.check.difficulty}. Бросить кубик?"
            + (
                "\nЕсли противник останется на ногах, он получит ответную попытку удара."
                if attempt["operation"] == "attack" and window._session.generated_world
                else ""
            )
            + (
                "\nДля перевязки будет использован один ваш бинт."
                if attempt["operation"] == "heal"
                else ""
            )
        ):
            cancel_narration(window)
            return
        cancel_narration(window)
        try:
            window._session.submit_actor_attempt(
                text,
                attempt["target_id"],
                attempt["operation"],
                attempt["lethal"],
                attempt["reason"],
                preview_record.model,
                confirmed_intent=True,
            )
            window._session.chronicle = memory_update
        except (ValueError, TypeError, KeyError) as error:
            failed(window, "Попытка не выполнена: " + str(error))
            return
        window.action_input.remember(text)
        window.action_input.clear()
        window._dirty = True
        window._refresh_character()
        window._render_journal()
        request_narration(window)
        return
    if queries:
        from rpg_vkr.storage.catalog import CatalogIndex

        if getattr(window, "_catalog_reads", 0) >= 1:
            failed(window, "Мастер исчерпал дополнительный поиск каталога. Ввод сохранён.")
            return
        index = CatalogIndex(window._session)
        try:
            found = []
            for query in queries:
                direct = index.lookup(query)
                found.extend([direct] if direct else index.search(query, limit=3))
        finally:
            index.close()
        state = catalog_context(window, text)
        results = found[:8]
        import json

        while results and len(json.dumps(results, ensure_ascii=False)) > 24000:
            results.pop()
        state["catalog_query_results"] = results
        window._catalog_reads += 1
        window.ollama.plan_world(
            build_frame(window._session),
            window.local_model.currentText(),
            text,
            state,
            window._session.campaign.world_brief,
        )
        return
    if hints.get("assessment"):
        request_challenge(window, text, assessment=hints["assessment"])
        return
    if category != "none":
        accept_challenge_suggestion(window, category)
        return
    if not plan.steps and not (definitions or entities):
        try:
            window._session.checked_memories(
                memories,
                window.ollama.response_model or window.local_model.currentText(),
                turn=len(window._session.turns) + 1,
            )
        except (ValueError, TypeError, KeyError) as error:
            failed(window, "Память не принята: " + str(error))
            return
        if hints.get("reply"):
            accept_inline_reply(window, text, hints["reply"])
            return
        if requests_physical_change(text):
            window._story_obstacle = (
                "План изменения мира не подтверждён. Объясни препятствие или уточни способ; "
                "не описывай успешное перемещение или получение предмета."
            )
        continue_story(window, text)
        return
    confirmation = False
    confirmation_reason = ""
    try:
        state = window._session.interaction_state()
        catalog = window._session.catalog
        if definitions or entities:
            record = Registration(
                definitions,
                entities,
                reason,
                window.ollama.response_model or window.local_model.currentText(),
                len(window._session.turns),
                state,
            )
            catalog, state = register(window._session.catalog or seed_catalog(), state, record)
        from rpg_vkr.domain.resources import activate, needed, physical

        if needed(state, plan, catalog, window._session.catalog_aliases):
            state = activate(state, window._session.world, catalog, window._session.catalog_aliases)
        if catalog or physical(state):
            validate_plan_properties(
                catalog or seed_catalog(),
                state,
                plan,
                turn_index=len(window._session.turns) + 1 + bool(definitions or entities),
                aliases=window._session.catalog_aliases,
            )
        after_preview, risky, _, _ = apply_plan(
            state, plan, turn_index=len(window._session.turns) + 1 + bool(definitions or entities)
        )
        memory_update = (
            window._session.checked_memories(
                memories,
                window.ollama.response_model or window.local_model.currentText(),
                scene=after_preview,
                turn=len(window._session.turns) + bool(plan.steps) + bool(definitions or entities),
            )
            if memories
            else window._session.chronicle
        )
        try:
            bind_plan(text, plan)
        except PlanConfirmationRequired as error:
            confirmation = True
            confirmation_reason = str(error)
    except (ValueError, TypeError, KeyError) as error:
        failed(window, "План не выполнен: " + str(error))
        return
    names = {t.id: t.name for t in state.things}
    names.update({p.id: p.name for p in window._session.interaction_state().places + plan.places})
    verbs = {
        "take": "Взять",
        "drop": "Оставить",
        "put": "Переложить",
        "give": "Передать",
        "move": "Перейти",
        "look": "Осмотреться",
        "inventory": "Инвентарь",
    }
    preview = "\n".join(verbs[s.op] + ": " + names.get(s.target, s.target) for s in plan.steps)
    question = (
        (
            "Попытка завладеть чужой вещью: проверка Ловкости, сложность 15. "
            "Свидетели могут стать враждебными. Бросить кубик?\n\n"
            if risky
            else "Мастер понял вашу формулировку так. Выполнить?\n\n"
        )
        + confirmation_reason
        + "\n"
        + preview
    )
    if (risky or confirmation) and not window._confirm(question):
        cancel_narration(window)
        window.narrator_status.setText("Попытка отменена; предметы и кубики не изменены.")
        return
    cancel_narration(window)
    try:
        if definitions or entities:
            window._session.register_catalog(text, definitions, entities, reason, record.model)
        if plan.steps:
            window._session.submit_interaction(
                text,
                plan,
                confirmed_plan=confirmation,
                origin="system" if definitions or entities else "typed",
            )
        window._session.chronicle = memory_update
    except (ValueError, TypeError, KeyError) as error:
        window.action_input.setText(text)
        failed(window, "План не выполнен: " + str(error))
        return
    window.action_input.remember(text)
    window.action_input.clear()
    window._dirty = True
    window._refresh_character()
    window._render_journal()
    window.narrator_status.setText("Вещи, место и последствия изменены в сохранённом состоянии.")
    if hints.get("reply") and not plan.steps:
        window._chat_text = text
        window._narrating_session = window._session
        window._narrating_index = len(window._session.turns)
        accept_inline_reply(window, text, hints["reply"])
    else:
        request_narration(window)


def request_challenge(window, text, *, suggested_kind=None, assessment=None):
    from rpg_vkr.domain.challenge import CHALLENGES, proposed_challenge
    from rpg_vkr.domain.character import ABILITY_NAMES

    kind = "general" if assessment else suggested_kind or proposed_challenge(text)
    if kind is None:
        return False
    cancel_narration(window)
    if window._session.combat.active or window._session.world.hp <= 0:
        window.narrator_status.setText(
            "Эта проверка недоступна во время схватки или после выбытия."
        )
        return True
    if assessment:
        from rpg_vkr.domain.challenge import validate_assessment

        validate_assessment(assessment)
        ability, difficulty, purpose = (assessment[k] for k in ("ability", "dc", "purpose"))
    else:
        ability, difficulty, purpose = CHALLENGES[kind]
    if not window._confirm(
        f"Чтобы {purpose}, предлагается проверка: {ABILITY_NAMES[ability]}, "
        f"сложность {difficulty}. Бросить кубик?\n\n"
        "Проверяется попытка; награды, вещи и переходы требуют отдельных правил."
    ):
        window.narrator_status.setText("Бросок отменён. Ваш текст остался в поле ввода.")
        return True
    try:
        window._session.submit_challenge(text, suggested_kind=suggested_kind, assessment=assessment)
    except ValueError as error:
        window.narrator_status.setText(str(error))
        return True
    window.action_input.remember(text)
    window.action_input.clear()
    window._dirty = True
    window._refresh_character()
    window._render_journal()
    window.narrator_status.setText("Проверка рассчитана. Итог и бросок сохранены в сессии.")
    if window.enable_local_narrator.isChecked() and window.ai_chat.isChecked():
        request_narration(window)
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


def accept_proposal(window, proposal, *, source=None):
    if (
        window._chat_text is None
        or window._narrating_session is not window._session
        or window._narrating_index != len(window._session.turns)
        or not window.enable_local_narrator.isChecked()
    ):
        return
    if proposal.mechanical_command:
        failed(window, "Рассказчик не имеет права выполнять игровые команды.")
        return
    text = window._chat_text
    try:
        source = (
            source
            or (getattr(window.ollama, "response_model", "") if window.ollama.cloud else "")
            or window.local_model.currentText()
        )
        memory_update = (
            window._session.checked_memories(
                getattr(window, "_pending_memories", []),
                source,
                turn=len(window._session.turns) + 1,
            )
            if getattr(window, "_pending_memories", None)
            else window._session.chronicle
        )
        window._session.submit_scene(
            text,
            proposal,
            source,
            base_turn=window._narrating_index,
            instruction_hash=window.ollama.instruction_hash
            if source != "local-clarification"
            else "",
        )
        window._session.chronicle = memory_update
        window._pending_memories = []
    except (ValueError, TypeError) as error:
        failed(window, str(error))
        return
    window._chat_text = None
    window._narrating_session = None
    window._narrating_index = None
    window.action_input.remember(text)
    window._dirty = True
    window._refresh_character()
    window._render_journal()
    window._model_turn_open = False
    window.narrator_status.setText("Рассказ сохранён в памяти сессии. Сохраните сессию в ячейку.")
    refresh_narrator_panels(window)


def export_campaign(window):
    import sqlite3
    from pathlib import Path

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from rpg_vkr.storage.knowledge import export_session

    filename, _ = QFileDialog.getSaveFileName(
        window, "Полная память кампании", "campaign.sqlite3", "SQLite (*.sqlite3)"
    )
    if not filename:
        return
    path = Path(filename)
    if path.resolve().is_relative_to(window._saves.directory.resolve()):
        QMessageBox.warning(window, "Экспорт отменён", "Выберите файл вне папки ячеек.")
        return
    try:
        export_session(window._session, path)
    except (OSError, ValueError, sqlite3.Error) as error:
        QMessageBox.warning(window, "Экспорт не выполнен", str(error))
        return
    window.statusBar().showMessage("Полная сессия и поисковые таблицы сохранены в SQLite.", 10000)


def import_campaign(window):
    import sqlite3

    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from rpg_vkr.storage.knowledge import restore_session

    filename, _ = QFileDialog.getOpenFileName(window, "Открыть кампанию", "", "SQLite (*.sqlite3)")
    if not filename:
        return
    try:
        session = restore_session(filename)
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        QMessageBox.warning(
            window, "Кампания не открыта", "Файл повреждён или имеет другой формат."
        )
        return
    if (window._dirty or window.action_input.text().strip()) and not window._confirm(
        "Открыть кампанию из базы? Несохранённая текущая сессия будет потеряна."
    ):
        return
    cancel_narration(window)
    window._session = session
    window._dirty = False
    window._current_slot = None
    window.action_input.clear()
    window._refresh_character()
    window._render_journal()
    window._rebuild_history()
    window._refresh_slots()


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
    window._model_turn_open = False
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


def record_model_event(window, event):
    repository = window._campaign_repository
    session = getattr(window, "_telemetry_session", window._session)
    base = getattr(window, "_model_base_turn", len(session.turns))
    event = {
        **event,
        "world_committed": any(
            t.interaction or t.catalog or t.trade or t.combat or t.challenge or t.intent
            for t in session.turns[base:]
        ),
    }
    if repository:
        try:
            repository.record_model_call(
                getattr(window, "_telemetry_session", window._session), event
            )
        except (ValueError, OSError, sqlite3.Error):
            window.narrator_metrics.setText(
                "Не удалось записать метрики; состояние игры сохранено отдельно."
            )
            return
    refresh_model_metrics(window)


def refresh_model_metrics(window):
    repository = window._campaign_repository
    try:
        rows = repository.model_stats(window._session) if repository else []
    except (ValueError, OSError, sqlite3.Error):
        return
    calls = [r for r in rows if r["event_type"] == "model_response"]
    total = sum(r["count"] for r in calls)
    rejected = sum(r["count"] for r in calls if r["outcome"] == "rejected")
    failed_count = sum(r["count"] for r in calls if r["outcome"] in {"failed", "cancelled"})
    inline = sum(
        r["count"]
        for r in rows
        if r["event_type"] == "prose_validation" and r["outcome"] == "rejected"
    )
    window.narrator_metrics.setText(
        f"Кампания: генераций {total}; отклонённых ответов {rejected}; "
        f"сбоев/отмен {failed_count}; отклонений встроенного рассказа {inline}. "
        "Приём формата плана не означает успех действия или оценку качества модели."
    )


def refresh_narrator_panels(window):
    if not hasattr(window, "ollama"):
        return
    session = window._session
    refresh_model_metrics(window)
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
    checking = window.routerai_catalog.busy or window.routerai_key_client.busy
    pending = getattr(window, "_flash_pending", False)
    window.cancel_narration_button.setEnabled(busy or checking or pending)
    window.find_models_button.setEnabled(not busy and not pending)
    window.routerai_catalog_button.setEnabled(not busy and not checking and not pending)
    window.routerai_model_list.setEnabled(not busy and not pending)
    from rpg_vkr.ui.connection_panel import refresh_connection_layout

    refresh_connection_layout(window)
    window.mode_label.setText("Мастер" if enabled else "Мастер · подключение выключено")
    frame = build_frame(session)
    context = (
        f"{frame.hero}\n{frame.location}; здоровье {frame.health}\n"
        f"Инвентарь: {frame.inventory}\n{frame.quest}\n\n{frame.scene}\n"
        + "\n".join(frame.visible_actors)
        + "\n\nПодтверждённый итог:\n"
        + frame.confirmed_result
        + "\n\nПоследние известные изменения:\n"
        + "\n".join(frame.memories)
        + (
            "\n\nПожелания к миру (не факты):\n" + session.campaign.world_brief
            if session.campaign.world_brief
            else ""
        )
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
