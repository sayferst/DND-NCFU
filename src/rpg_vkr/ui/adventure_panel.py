"""Notebook editing, durable recall and asynchronous world creation."""

import json
import sqlite3

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.domain.adventure import build_world, offline_world


def install_adventure_panel(window):
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.addWidget(
        QLabel(
            "Личные записи героя. Это ваши сведения и предположения; они не "
            "меняют мир сами по себе."
        )
    )
    window.diary_search = QLineEdit()
    window.diary_search.setPlaceholderText("Найти по имени, месту, траве или товару")
    layout.addWidget(window.diary_search)
    window.diary_list = QListWidget()
    layout.addWidget(window.diary_list, 1)
    window.diary_title = QLineEdit()
    window.diary_title.setPlaceholderText("Заголовок заметки")
    window.diary_place = QLineEdit()
    window.diary_place.setPlaceholderText("Место или источник сведений")
    window.diary_text = QPlainTextEdit()
    window.diary_text.setPlaceholderText(
        "Где растут травы, цена в городе, имя, сведения от информатора…"
    )
    window.diary_pin = QCheckBox("Важное: держать в памяти мастера")
    for widget in (window.diary_title, window.diary_place, window.diary_text, window.diary_pin):
        layout.addWidget(widget)
    row = QHBoxLayout()
    for name, title, callback in (
        ("diary_new", "Новая заметка", lambda: new_note(window)),
        ("diary_save", "Сохранить заметку", lambda: save_note(window)),
        ("diary_delete", "Удалить заметку", lambda: delete_note(window)),
    ):
        button = QPushButton(title)
        button.clicked.connect(callback)
        setattr(window, name, button)
        row.addWidget(button)
    layout.addLayout(row)
    window.diary_status = QLabel()
    window.diary_status.setWordWrap(True)
    layout.addWidget(window.diary_status)
    archive_row = QHBoxLayout()
    window.campaign_choice = QComboBox()
    window.recover_campaign = QPushButton("Открыть рабочую кампанию из базы")
    window.recover_campaign.clicked.connect(lambda: recover(window))
    archive_row.addWidget(window.campaign_choice, 1)
    archive_row.addWidget(window.recover_campaign)
    if window._legacy_controls:
        layout.addLayout(archive_row)
    else:
        window.saves_layout.insertLayout(0, archive_row)
    window.generate_world_button = QPushButton("Создать мир мастером для нового героя")
    window.generate_world_button.clicked.connect(lambda: begin_world(window))
    layout.addWidget(window.generate_world_button)
    window.world_generation_status = QLabel()
    window.world_generation_status.setWordWrap(True)
    layout.addWidget(window.world_generation_status)
    window.memory_query = QLineEdit()
    window.memory_query.setPlaceholderText("Поиск в памяти кампании")
    window.memory_find = QPushButton("Вспомнить")
    window.memory_find.clicked.connect(lambda: find_memory(window))
    window.memory_query.returnPressed.connect(lambda: find_memory(window))
    layout.addWidget(window.memory_query)
    layout.addWidget(window.memory_find)
    window.memory_results = QPlainTextEdit()
    window.memory_results.setReadOnly(True)
    window.memory_results.setMaximumHeight(160)
    layout.addWidget(window.memory_results)
    window._diary_id = None
    window._diary_session = None
    window._diary_records = []
    window._diary_draft = False
    window._filling_diary = False

    def changed():
        if not window._filling_diary:
            window._diary_draft = True

    window.diary_title.textChanged.connect(changed)
    window.diary_place.textChanged.connect(changed)
    window.diary_text.textChanged.connect(changed)
    window.diary_pin.toggled.connect(changed)
    window.diary_search.textChanged.connect(lambda _: refresh_diary(window))
    window.diary_list.currentRowChanged.connect(lambda row: select_note(window, row))
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    page.setMinimumHeight(820)
    scroll.setWidget(page)
    window.tabs.addTab(scroll, "Дневник")
    window.ollama.world_seed_ready.connect(lambda value: accept_world(window, value))


def refresh_diary(window):
    if not hasattr(window, "diary_list"):
        return
    if window._diary_session is not window._session:
        window._diary_session = window._session
        new_note(window, force=True)
    selected = window._diary_id
    query = window.diary_search.text().strip().casefold()
    entries = window._session.chronicle.entries if window._session.chronicle else ()
    window._diary_records = [
        e for e in entries if query in (e.title + " " + e.text + " " + e.place).casefold()
    ]
    window.diary_list.blockSignals(True)
    window.diary_list.clear()
    for entry in window._diary_records:
        window.diary_list.addItem(
            ("★ " if entry.pinned else "") + entry.title + " · " + entry.place
        )
    index = next((i for i, e in enumerate(window._diary_records) if e.id == selected), -1)
    window.diary_list.setCurrentRow(index)
    window.diary_list.blockSignals(False)
    window.generate_world_button.setEnabled(
        window._session.progress.enabled
        and not window._session.turns
        and not window._session.generated_world
        and not getattr(window, "_generating_session", None)
    )
    error = getattr(window, "_archive_error", "")
    window.diary_status.setText(error or "Рабочая память: " + str(window._campaign_repository.path))


def discard_draft(window):
    return not window._diary_draft or window._confirm(
        "Отбросить несохранённые изменения заметки? Они будут потеряны."
    )


def new_note(window, *, force=False):
    if not force and not discard_draft(window):
        return
    window._filling_diary = True
    window._diary_id = None
    window.diary_title.clear()
    window.diary_text.clear()
    window.diary_place.setText(window._session.current_place_name)
    window.diary_pin.setChecked(False)
    window.diary_delete.setEnabled(False)
    window._filling_diary = False
    window._diary_draft = False


def select_note(window, row):
    if not 0 <= row < len(window._diary_records):
        return
    if not discard_draft(window):
        return
    window._filling_diary = True
    entry = window._diary_records[row]
    window._diary_id = entry.id
    window.diary_title.setText(entry.title)
    window.diary_text.setPlainText(entry.text)
    window.diary_place.setText(entry.place)
    window.diary_pin.setChecked(entry.pinned)
    window.diary_delete.setEnabled(True)
    window._filling_diary = False
    window._diary_draft = False


def save_note(window):
    try:
        window._session.write_diary(
            window.diary_title.text().strip(),
            window.diary_text.toPlainText(),
            id=window._diary_id,
            pinned=window.diary_pin.isChecked(),
            place=window.diary_place.text(),
        )
    except ValueError as error:
        window.diary_status.setText("Заметка не сохранена: " + str(error))
        return
    window._diary_id = window._session.chronicle.diary[-1].id
    window._diary_draft = False
    window._dirty = True
    window._persist_campaign()
    refresh_diary(window)
    window.diary_delete.setEnabled(True)


def delete_note(window):
    if not window._diary_id or not window._confirm("Удалить эту заметку из дневника?"):
        return
    old = next(e for e in window._session.chronicle.entries if e.id == window._diary_id)
    window._session.write_diary(
        old.title, old.text, id=old.id, pinned=old.pinned, delete=True, place=old.place
    )
    window._dirty = True
    new_note(window, force=True)
    window._persist_campaign()
    refresh_diary(window)


def find_memory(window):
    if not window._campaign_repository:
        window.memory_results.setPlainText(window._archive_error)
        return
    try:
        value = window._campaign_repository.recall(window._session, window.memory_query.text())
        window.memory_results.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))
    except (OSError, ValueError, sqlite3.Error) as error:
        window.memory_results.setPlainText("Память недоступна: " + str(error))


def recover(window):
    id = window.campaign_choice.currentData()
    if not id or not window._campaign_repository:
        return
    if (window._dirty or window._diary_draft) and not window._confirm(
        "Открыть рабочую копию из базы вместо текущей сессии?"
    ):
        return
    try:
        session = window._campaign_repository.load(id)
    except (OSError, ValueError, sqlite3.Error) as error:
        window.diary_status.setText("Кампания не открыта: " + str(error))
        return
    window._generating_session = None
    window.ollama.cancel()
    window._session = session
    window._dirty = True
    window._current_slot = None
    window.action_input.setEnabled(True)
    window.action_input.clear()
    window._refresh_character()
    window._render_journal()
    window.resume_session()


def begin_world(window):
    from rpg_vkr.ui.narrator_panel import cancel_narration, prepare_model

    session = window._session
    if not session.progress.enabled or session.turns or session.generated_world:
        window.world_generation_status.setText("Создайте нового героя, чтобы начать новый мир.")
        return
    cancel_narration(window)
    window._generating_session = session
    window._world_seed_attempts = 0
    window.ollama.begin_turn()
    window._telemetry_session = session
    window._model_base_turn = 0
    window.action_input.setEnabled(False)
    window.send_button.setEnabled(False)
    if window.enable_local_narrator.isChecked() and prepare_model(window):
        request_world(window)
    else:
        finish_world(
            window,
            offline_world(session),
            (
                "Создан автономный случайный старт. Для ИИ-генерации включите "
                "мастера перед созданием следующего героя."
            ),
        )


def request_world(window, error=""):
    from rpg_vkr.narrative.context import build_frame

    session = window._session
    window._world_seed_attempts += 1
    window.world_generation_status.setText("Мастер создаёт район и сюжетные зацепки…")
    window.ollama.generate_world(
        build_frame(session),
        window.local_model.currentText(),
        {
            "hero": session.character.name,
            "class": session.progress.class_id,
            "hero_description": session.campaign.raw_player_description,
            "world_brief": session.campaign.world_brief,
            "variation": session.campaign.world_id,
        },
        error,
    )
    window._render_journal()


def accept_world(window, value):
    if getattr(window, "_generating_session", None) is not window._session:
        return
    try:
        seed = build_world(
            value, window._session, window.ollama.response_model or window.local_model.currentText()
        )
    except (ValueError, TypeError, KeyError) as error:
        if window._world_seed_attempts < 2:
            request_world(window, str(error))
        else:
            generation_failed(window, "Модель дважды нарушила формат: " + str(error))
        return
    finish_world(
        window, seed, "Мир создан мастером. Сюжетный замысел сохранён отдельно от знаний героя."
    )


def finish_world(window, seed, status):
    if getattr(window, "_generating_session", None) is not window._session:
        return
    window._session.start_world(seed)
    window._generating_session = None
    window.action_input.setEnabled(True)
    window.send_button.setEnabled(bool(window.action_input.text().strip()))
    window._dirty = True
    window.world_generation_status.setText(status)
    window.narrator_status.setText(status)
    window._refresh_character()
    window._render_journal()
    window.resume_session()


def generation_failed(window, message):
    if getattr(window, "_generating_session", None) is window._session:
        finish_world(
            window,
            offline_world(window._session),
            "ИИ-генерация не завершилась: "
            + message
            + " Создан автономный старт; описание героя сохранено.",
        )
