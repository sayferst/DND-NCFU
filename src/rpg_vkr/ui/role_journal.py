"""Plain text remains inert; role metadata alone controls accessible message colours."""

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
from rpg_vkr.domain.combat import ANGER_COMMANDS, NAMES_TO_IDS, disposition_label
from rpg_vkr.domain.world import OBSERVE_COMMANDS
from rpg_vkr.narrative.presentation import present_turn


class MessageRole(QTextBlockUserData):
    def __init__(self, role: str, actor_id: str | None = None) -> None:
        super().__init__()
        self.role = role
        self.actor_id = actor_id


class RoleHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.dark = False
        self.hostile_ids = set()

    def highlightBlock(self, text: str) -> None:
        metadata = self.currentBlock().userData()
        role = metadata.role if isinstance(metadata, MessageRole) else "system"
        hostile = isinstance(metadata, MessageRole) and metadata.actor_id in self.hostile_ids
        format = QTextCharFormat()
        format.setForeground(self.colour("hostile" if hostile else role))
        if hostile:
            format.setFontWeight(QFont.Weight.Bold)
        self.setFormat(0, len(text), format)

    def colour(self, role):
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

    def set_role_theme(self, dark: bool) -> None:
        self.highlighter.dark = dark
        self.highlighter.rehighlight()

    def append_message(
        self, role: str, label: str, text: str, *, blank_before=False, actor_id=None
    ) -> None:
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if not self.document().isEmpty():
            cursor.insertBlock()
            if blank_before:
                cursor.insertBlock()
        first_block = cursor.block().blockNumber()
        cursor.insertText(f"{label}: {text}")
        last_block = cursor.block().blockNumber()
        block = self.document().findBlockByNumber(first_block)
        while block.isValid() and block.blockNumber() <= last_block:
            block.setUserData(MessageRole(role, actor_id))
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

    def append_turn(self, turn) -> None:
        self.append_message("player", "Вы", turn.action, blank_before=True)
        if turn.combat is not None:
            role = "system"
        elif turn.actor_id is not None:
            role = "npc"
        elif turn.speaker in {"Мир", "Рассказчик"}:
            role = "narrator"
        else:
            role = "system"
        if turn.speaker == "Мир" and normalise_action(turn.action) in OBSERVE_COMMANDS:
            # Only engine-authored observation rows carry these identities. Player text
            # is always inserted above with role=player, never inspected for identities.
            for line in turn.text.splitlines():
                name, separator, body = line.partition(": ")
                actor_id = NAMES_TO_IDS.get(name) if separator else None
                self.append_message(
                    "npc" if actor_id else role,
                    name if actor_id else turn.speaker,
                    body if actor_id else line,
                    actor_id=actor_id,
                )
            return
        # NPC identity already labels the message; do not duplicate it in its body.
        text = present_turn(turn).story
        if role == "npc" and text.startswith(turn.speaker + ":"):
            text = text[len(turn.speaker) + 1 :].lstrip()
        context = (
            "Провокация — "
            if turn.combat and turn.combat.command in ANGER_COMMANDS
            else "Схватка — "
        )
        label = (context if turn.combat else "") + turn.speaker
        if (
            turn.combat
            and turn.actor_id
            and turn.combat.outcome.state.actor(turn.actor_id).disposition == "hostile"
        ):
            label += " [" + disposition_label(turn.combat.outcome.state.actor(turn.actor_id)) + "]"
        self.append_message(role, label, text, actor_id=turn.actor_id)
