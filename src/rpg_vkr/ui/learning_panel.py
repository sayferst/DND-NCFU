"""Authenticated, explicit local library work. No startup jobs or model calls."""

import json
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from rpg_vkr.learning.library import Library, activate, active_path, build, default_directory
from rpg_vkr.learning.settings import load, update


class Signals(QObject):
    done = Signal(int, object)
    failed = Signal(int, str)
    progress = Signal(int, int)


class Task(QRunnable):
    def __init__(self, id, operation, cancel, signals):
        super().__init__()
        self.id, self.operation, self.cancel, self.signals = id, operation, cancel, signals

    def run(self):
        try:
            result = self.operation(
                self.cancel.is_set, lambda n: self.signals.progress.emit(self.id, n)
            )
            self.signals.done.emit(self.id, result)
        except InterruptedError:
            self.signals.failed.emit(self.id, "Задача отменена. Прежние данные сохранены.")
        except Exception as error:
            # Avoid raw contents, local paths or secrets in diagnostics.
            self.signals.failed.emit(
                self.id, "Локальная операция не выполнена: " + type(error).__name__
            )


class LearningPanel(QWidget):
    def __init__(self, console, *, directory=None):
        super().__init__()
        self.console = console
        self.directory = directory or default_directory()
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.signals = Signals(self)
        self.signals.done.connect(self.finished)
        self.signals.failed.connect(self.failed)
        self.signals.progress.connect(self.progress)
        self.cancel = Event()
        self.serial, self.busy, self.closing = 0, False, False
        self.rows, self.offset, self.selected = [], 0, ""
        layout = QVBoxLayout(self)
        note = QLabel(
            "Локальная библиотека · исходники не отправляются провайдеру. "
            "Импорт и поиск запускаются кнопками. Допуск выдержки требует вашей проверки."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.mode = QComboBox()
        self.mode.addItems(["Выключено", "Теневой поиск", "Подсказки в ответе"])
        self.mode.setCurrentIndex(load()["mode"])
        layout.addWidget(self.mode)
        self.flags = {}
        for key, label in (
            ("library", "Поиск по проверенным выдержкам"),
            ("memory", "Память подтверждённых событий"),
            ("templates", "Ручные предложения каталога"),
        ):
            box = QCheckBox(label)
            box.setChecked(load()[key])
            self.flags[key] = box
            layout.addWidget(box)
        self.button(layout, "Сохранить режим", self.save_flags)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.button(row, "Импорт ZIP…", self.import_zip)
        self.button(row, "Состояние", self.stats)
        self.button(row, "Перестроить индекс", self.rebuild)
        self.button(row, "Отмена задачи", lambda: self.cancel.set())
        row = QHBoxLayout()
        layout.addLayout(row)
        self.revision = QComboBox()
        row.addWidget(self.revision)
        self.button(row, "Версии", self.versions)
        self.button(row, "Выбрать версию", self.rollback)
        self.query = QLineEdit()
        self.query.setPlaceholderText("Поиск по названию/ID; выдержки — отдельной кнопкой")
        layout.addWidget(self.query)
        self.query.textChanged.connect(self.reset_page)
        self.namespace = QComboBox()
        self.namespace.addItems(
            [
                "",
                "narrative",
                "consequences",
                "events",
                "behavior",
                "entities",
                "adjudication",
                "crafting",
            ]
        )
        self.namespace.currentIndexChanged.connect(self.reset_page)
        layout.addWidget(self.namespace)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.button(row, "Карточки", self.browse)
        self.button(row, "Следующие 30", self.next_page)
        self.button(row, "Проверенный поиск", self.search)
        self.results = QListWidget()
        self.results.setMaximumHeight(120)
        self.results.itemActivated.connect(self.open_record)
        layout.addWidget(self.results)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMaximumHeight(180)
        layout.addWidget(self.preview)
        self.excerpt = QPlainTextEdit()
        self.excerpt.setPlaceholderText(
            "Проверенная безопасная выдержка до600символов; без числовых правил"
        )
        self.excerpt.setMaximumHeight(80)
        layout.addWidget(self.excerpt)
        self.reviewer = QLineEdit()
        self.reviewer.setPlaceholderText("Имя проверяющего (локальный журнал)")
        layout.addWidget(self.reviewer)
        row = QHBoxLayout()
        layout.addLayout(row)
        self.button(row, "Одобрить локально", lambda: self.review(True))
        self.button(row, "Отклонить / отозвать допуск", lambda: self.review(False))
        self.button(row, "Предложение шаблона", self.template_preview)
        self.status = QLabel("Библиотека не открывалась. Новые функции по умолчанию выключены.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def button(self, layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)

    def allowed(self):
        return self.console.access.authorized and not self.closing

    def start(self, operation):
        if not self.allowed() or self.busy:
            return False
        self.serial += 1
        self.cancel = Event()
        self.busy = True
        self.status.setText("Локальная задача выполняется…")
        self.pool.start(Task(self.serial, operation, self.cancel, self.signals))
        return True

    def progress(self, serial, count):
        if self.allowed() and serial == self.serial and self.busy:
            self.status.setText(f"Обработано этапов: {count}. Можно отменить.")

    def finished(self, serial, result):
        if serial != self.serial or self.closing:
            return
        self.busy = False
        if not self.allowed():
            return
        kind, value = result
        self.status.setText("Локальная операция завершена.")
        if kind == "rows":
            self.rows = value
            self.results.clear()
            self.results.addItems(
                [r["id"] + " · " + r["quality"] + " · " + r["split"] for r in value]
            )
        else:
            self.preview.setPlainText(json.dumps(value, ensure_ascii=False, indent=2))

    def failed(self, serial, error):
        if serial == self.serial and not self.closing:
            self.busy = False
            if self.allowed():
                self.status.setText(error)

    def call(self, function, *, writable=False):
        def operation(cancelled, progress):
            if cancelled():
                raise InterruptedError()
            with Library(active_path(self.directory), writable=writable) as db:
                return function(db, cancelled)

        return self.start(operation)

    def save_flags(self):
        if not self.allowed():
            return
        try:
            values = update(
                {
                    "mode": self.mode.currentIndex(),
                    **{key: box.isChecked() for key, box in self.flags.items()},
                }
            )
            window = self.console.window
            window._session._learning_flags = values
            window._session._rag_mode = values["mode"]
            window.rag_mode.setCurrentIndex(values["mode"])
            self.status.setText("Режим сохранён. Выключение не меняет кампании и сохранения.")
        except (OSError, ValueError):
            self.status.setText("Настройки не сохранены.")

    def import_zip(self):
        if not self.allowed() or self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Локальный учебный архив", "", "ZIP (*.zip)")
        if path:
            self.start(
                lambda cancel, progress: (
                    "result",
                    build(path, self.directory, cancelled=cancel, progress=progress),
                )
            )

    def stats(self):
        self.call(lambda db, _: ("result", db.stats()))

    def rebuild(self):
        self.call(lambda db, cancel: ("result", db.rebuild_index(cancelled=cancel)), writable=True)

    def versions(self):
        if self.allowed() and not self.busy:
            self.revision.clear()
            self.revision.addItems(
                [p.name for p in sorted(self.directory.glob("corpus-*.sqlite3"))]
            )

    def rollback(self):
        revision = self.revision.currentText()
        if not revision:
            return

        def operation(cancel, progress):
            if cancel():
                raise InterruptedError()
            activate(self.directory, self.directory / revision)
            return "result", {"active": revision}

        self.start(operation)

    def browse(self):
        query, space, offset = self.query.text(), self.namespace.currentText(), self.offset
        self.call(lambda db, _: ("rows", db.candidates(query, namespace=space, offset=offset)))

    def next_page(self):
        if not self.busy:
            self.offset = self.offset + 30 if self.rows else 0
            self.browse()

    def reset_page(self, *_):
        self.offset = 0

    def search(self):
        query = self.query.text()
        self.call(lambda db, _: ("result", db.search(query)))

    def open_record(self, item):
        index = self.results.row(item)
        if 0 <= index < len(self.rows) and not self.busy:
            self.selected = self.rows[index]["id"]
            record_id = self.selected
            self.excerpt.clear()
            self.call(lambda db, _: ("result", db.record(record_id)))

    def review(self, approved):
        id, text, reviewer = self.selected, self.excerpt.toPlainText().strip(), self.reviewer.text()
        if not id:
            return

        def operation(db, cancel):
            db.review(
                id, text, reviewer=reviewer, approved=approved, reason="Локальная ручная проверка"
            )
            return "result", {"id": id, "approved_local": approved, "external_transfer": False}

        self.call(operation, writable=True)

    def template_preview(self):
        if self.selected:
            from rpg_vkr.learning.templates import candidate

            record_id = self.selected
            self.call(lambda db, _: ("result", candidate(db, record_id)))

    def shutdown(self):
        self.closing = True
        self.cancel.set()
        self.pool.clear()
        # Workers do not reference widgets; wait for cancellation before QObject destruction.
        self.pool.waitForDone()
