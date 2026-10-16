"""Plain text remains inert; role metadata alone controls accessible message colours."""

from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextBlockUserData, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit


class MessageRole(QTextBlockUserData):
    def __init__(self, role: str) -> None:
        super().__init__()
        self.role = role


class RoleHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.dark = False

    def highlightBlock(self, text: str) -> None:
        metadata = self.currentBlock().userData()
        role = metadata.role if isinstance(metadata, MessageRole) else "system"
        colors = (
            {"player": "#8dbbff", "narrator": "#c8e6c9", "npc": "#e9b4ff", "system": "#bbbbbb"}
            if self.dark
            else {"player": "#174c91", "narrator": "#245632", "npc": "#783b81", "system": "#53516c"}
        )
        self.setFormat(0, len(text), QColor(colors[role]))


class RoleJournal(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.highlighter = RoleHighlighter(self.document())

    def set_role_theme(self, dark: bool) -> None:
        self.highlighter.dark = dark
        self.highlighter.rehighlight()

    def append_message(self, role: str, label: str, text: str, *, blank_before=False) -> None:
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
            block.setUserData(MessageRole(role))
            self.highlighter.rehighlightBlock(block)
            block = block.next()
        self.setTextCursor(cursor)

    def append_turn(self, turn) -> None:
        self.append_message("player", "Вы", turn.action, blank_before=True)
        if turn.speaker in {"Стражник", "Жительница", "Торговец"}:
            role = "npc"
        elif turn.speaker in {"Мир", "Рассказчик"}:
            role = "narrator"
        else:
            role = "system"
        # NPC identity already labels the message; do not duplicate it in its body.
        text = turn.text
        if role == "npc" and text.startswith(turn.speaker + ":"):
            text = text[len(turn.speaker) + 1 :].lstrip()
        self.append_message(role, turn.speaker, text)
