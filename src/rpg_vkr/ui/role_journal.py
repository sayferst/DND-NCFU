"""Plain text remains inert; role metadata alone controls accessible message colours."""

import re

from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextBlockUserData,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import QPlainTextEdit

from rpg_vkr.commands import normalise_action
from rpg_vkr.domain.combat import NAMES_TO_IDS
from rpg_vkr.domain.world import OBSERVE_COMMANDS
from rpg_vkr.narrative.presentation import present_turn
from rpg_vkr.narrative.segments import split_story


class MessageRole(QTextBlockUserData):
    def __init__(self, role: str, actor_id: str | None = None, speech_only=False) -> None:
        super().__init__()
        self.role = role
        self.actor_id = actor_id
        self.speech_only = speech_only


class RoleHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.dark = False
        self.hostile_ids = set()
        self.colors = None

    def highlightBlock(self, text: str) -> None:
        metadata = self.currentBlock().userData()
        role = metadata.role if isinstance(metadata, MessageRole) else "system"
        speech_only = isinstance(metadata, MessageRole) and metadata.speech_only
        hostile = (
            isinstance(metadata, MessageRole)
            and metadata.actor_id in self.hostile_ids
            and not speech_only
        )
        format = QTextCharFormat()
        format.setForeground(self.colour("hostile" if hostile else role))
        if hostile:
            format.setFontWeight(QFont.Weight.Bold)
        self.setFormat(0, len(text), format)
        if self.colors and role == "narrator" and text.startswith("Мастер:"):
            caption = QTextCharFormat()
            caption.setForeground(self.colour("secondary"))
            self.setFormat(0, len("Мастер:"), caption)
        if (
            self.colors
            and role == "narrator"
            and (text.startswith("// ") or " | " in text and len(text) < 160)
        ):
            heading = QTextCharFormat()
            heading.setForeground(self.colour("important"))
            heading.setFontWeight(QFont.Weight.Bold)
            self.setFormat(0, len(text), heading)
        if speech_only and metadata.actor_id:
            speech_format = QTextCharFormat()
            is_hostile = metadata.actor_id in self.hostile_ids
            speech_format.setForeground(self.colour("hostile" if is_hostile else "npc"))
            if is_hostile:
                speech_format.setFontWeight(QFont.Weight.Bold)
            for match in re.finditer(r"«[^»]+»|(?:^|: )— .+$", text):
                self.setFormat(match.start(), len(match[0]), speech_format)

    def colour(self, role):
        if self.colors is not None:
            return QColor(self.colors[role])
        colors = (
            {
                "player": "#8dbbff",
                "narrator": "#9fe0b5",
                "npc": "#e9a4ff",
                "system": "#c8c8d8",
                "hostile": "#ff737d",
            }
            if self.dark
            else {
                "player": "#064fc4",
                "narrator": "#146336",
                "npc": "#8a2ba4",
                "system": "#53516c",
                "hostile": "#b00020",
            }
        )
        return QColor(colors[role])


class RoleJournal(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.highlighter = RoleHighlighter(self.document())
        self.hero_name = "Путник"

    def set_role_theme(self, dark: bool) -> None:
        self.highlighter.dark = dark
        self.highlighter.rehighlight()

    def set_journal_palette(self, colors):
        self.highlighter.colors = dict(colors)
        self.setStyleSheet(
            "QPlainTextEdit { background: "
            + colors["background"]
            + "; color: "
            + colors["narrator"]
            + "; }"
        )
        self.highlighter.rehighlight()

    def append_message(
        self,
        role: str,
        label: str,
        text: str,
        *,
        blank_before=False,
        actor_id=None,
        speech_only=False,
    ) -> None:
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.document().isEmpty():
            cursor.insertBlock()
            if blank_before:
                cursor.insertBlock()
        first_block = cursor.block().blockNumber()
        cursor.insertText(f"{label}: {text}" if label else text)
        last_block = cursor.block().blockNumber()
        block = self.document().findBlockByNumber(first_block)
        while block.isValid() and block.blockNumber() <= last_block:
            block.setUserData(MessageRole(role, actor_id, speech_only))
            self.highlighter.rehighlightBlock(block)
            block = block.next()
        self.setTextCursor(cursor)

    def set_hostiles(self, actor_ids):
        self.highlighter.hostile_ids = set(actor_ids)
        self.highlighter.rehighlight()

    def actor_colour(self, actor_id):
        return self.highlighter.colour(
            "hostile" if actor_id in self.highlighter.hostile_ids else "npc"
        )

    def append_player(self, turn):
        if turn.origin in {"typed", "legacy"}:
            self.append_message(
                "player", turn.player_name or self.hero_name, turn.action, blank_before=True
            )

    def append_story(self, text, *, actor_id=None):
        self.append_segments(split_story(text, actor_id))

    def append_master_story(self, text, *, actor_id=None):
        # One label for the whole turn; quoted NPC speech keeps its own colour.
        self.append_message("narrator", "Мастер", text, actor_id=actor_id, speech_only=True)

    def append_segments(self, segments):
        for segment in segments:
            self.append_message(
                "narrator" if segment.speaker_id == "master" else "npc",
                segment.display_name,
                segment.text,
                actor_id=None if segment.speaker_id == "master" else segment.speaker_id,
            )

    def append_turn(self, turn) -> None:
        self.append_player(turn)
        if (
            turn.speaker == "Мир"
            and normalise_action(turn.intent or turn.action) in OBSERVE_COMMANDS
        ):
            for index, line in enumerate(turn.text.splitlines()):
                name, separator, body = line.partition(": ")
                actor_id = NAMES_TO_IDS.get(name) if separator else None
                if actor_id and "нейтрал" in body and "без видимых ран" in body:
                    body = "рядом."
                self.append_message(
                    "npc" if actor_id else "narrator",
                    "Мастер" if index == 0 else None,
                    f"{name} {body}" if actor_id else line,
                    actor_id=actor_id,
                )
            return
        text = present_turn(turn).story
        if turn.combat:
            self.append_master_story(text)
        elif turn.dialogue:
            text = text.removeprefix(turn.speaker + ": ")
            self.append_story(text, actor_id=turn.actor_id)
        else:
            role = "npc" if turn.actor_id else "narrator"
            self.append_message(
                role,
                turn.speaker if turn.actor_id else "Мастер",
                text.removeprefix(turn.speaker + ": ") if turn.actor_id else text,
                actor_id=turn.actor_id,
            )
