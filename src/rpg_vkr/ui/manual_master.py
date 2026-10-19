"""Explicit copy/paste bridge for a user's ChatGPT chat; no account access or API."""

import json
import uuid

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from rpg_vkr.domain.conflict import peaceful_contact
from rpg_vkr.domain.director import Proposal
from rpg_vkr.narrative.context import build_frame
from rpg_vkr.narrative.director import MASTER_CONTRACT, proposal_schema
from rpg_vkr.narrative.master import campaign_context
from rpg_vkr.storage.knowledge import retrieve


def create_packet(session, text, *, prose=False):
    request_id = uuid.uuid4().hex
    packet = {
        "request_id": request_id,
        "instruction": MASTER_CONTRACT
        + (
            ' Верни только JSON-объект {"request_id": исходный request_id, "proposal": '
            "предложение по proposal_schema}. Без markdown-ограждений. "
            "Если это предыдущая кампания, текущий пакет имеет приоритет."
        ),
        "proposal_schema": proposal_schema(),
        "world_id": session.campaign.world_id,
        "revision": len(session.turns),
        "player_message": text,
        "scene": build_frame(session).to_dict(),
        "campaign": {k: v for k, v in campaign_context(session).items() if k != "constraints"},
        "memory": retrieve(session, text),
        "reaction_model": peaceful_contact(),
    }

    if prose:
        from rpg_vkr.narrative.ollama import SYSTEM_PROMPT

        packet["instruction"] = (
            SYSTEM_PROMPT
            + " Действие УЖЕ выполнено. Опиши confirmed_result, не бросай кубики заново. "
            'Верни JSON {"request_id": исходный request_id, '
            '"proposal": {"narration": художественный итог}}. Без markdown.'
        )
        packet["proposal_schema"] = {
            "type": "object",
            "properties": {"narration": {"type": "string", "maxLength": 1500}},
            "required": ["narration"],
            "additionalProperties": False,
        }
    packet["stage"] = "confirmed_result" if prose else "scene_proposal"
    return packet


def parse_response(text, request_id, *, prose=False):
    if len(text) > 20000:
        raise ValueError("Ответ слишком большой.")
    text = text.strip()
    if text.startswith("```json\n") and text.endswith("```"):
        text = text[8:-3].strip()
    value = json.loads(text)
    if (
        not isinstance(value, dict)
        or set(value) != {"request_id", "proposal"}
        or value["request_id"] != request_id
    ):
        raise ValueError("Ответ относится к другому запросу или имеет неверный формат.")
    if prose:
        result = value["proposal"]
        if not isinstance(result, dict) or set(result) != {"narration"}:
            raise ValueError("Нужен только художественный итог уже выполненного действия.")
        return result
    return Proposal.from_dict(value["proposal"])


def open_exchange(window, text, *, prose=False):
    packet = create_packet(window._session, text, prose=prose)
    frame = build_frame(window._session)
    session, revision = window._session, len(window._session.turns)
    dialog = QDialog(window)
    dialog.setWindowTitle("ChatGPT вручную — без API")
    dialog.resize(800, 650)
    layout = QVBoxLayout(dialog)
    label = QLabel(
        "1. Скопируйте запрос и вставьте в ChatGPT.\n"
        "2. Полученный JSON вставьте ниже и нажмите «Применить».\n"
        "Передача в ChatGPT происходит только вручную."
    )
    label.setWordWrap(True)
    layout.addWidget(label)
    request = QPlainTextEdit(json.dumps(packet, ensure_ascii=False, indent=2))
    request.setReadOnly(True)
    layout.addWidget(request)
    copy = QPushButton("Копировать запрос для ChatGPT")
    copy.clicked.connect(lambda: QApplication.clipboard().setText(request.toPlainText()))
    layout.addWidget(copy)
    response = QPlainTextEdit()
    response.setPlaceholderText("Вставьте JSON-ответ ChatGPT целиком…")
    layout.addWidget(response)
    apply = QPushButton("Проверить и применить ответ")
    layout.addWidget(apply)

    def commit():
        if (
            window._session is not session
            or len(session.turns) != revision
            or (not prose and window._chat_text != text)
            or window._narrating_session is not session
        ):
            QMessageBox.warning(dialog, "Ответ устарел", "Подготовьте запрос для текущей сессии.")
            return
        try:
            proposal = parse_response(response.toPlainText(), packet["request_id"], prose=prose)
        except (ValueError, TypeError, KeyError) as error:
            QMessageBox.warning(dialog, "Ответ не принят", str(error))
            return
        if prose:
            from rpg_vkr.narrative.ollama import parse_narration
            from rpg_vkr.ui.narrator_panel import accept_narration

            try:
                note = parse_narration(
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(proposal, ensure_ascii=False),
                        }
                    },
                    frame,
                    "chatgpt-manual",
                )
                accept_narration(window, note)
            except (ValueError, TypeError) as error:
                QMessageBox.warning(dialog, "Итог не принят", str(error))
                return
        else:
            from rpg_vkr.ui.narrator_panel import accept_proposal

            accept_proposal(window, proposal)
        if window._chat_text is None:
            dialog.accept()

    def closed():
        if (window._chat_text == text or prose) and window._narrating_session is session:
            from rpg_vkr.ui.narrator_panel import cancel_narration

            cancel_narration(window)

    apply.clicked.connect(commit)
    dialog.rejected.connect(closed)
    window.manual_dialog = dialog
    # Exposed widgets also support offscreen acceptance checks, without clipboard I/O.
    dialog.request_packet = packet
    dialog.response_editor = response
    dialog.apply_response = apply
    dialog.show()
