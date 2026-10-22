"""Visual chat routing without calling the text model or executing a world action."""

import re
from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog

from rpg_vkr.ui.knowledge import knowledge_entries
from rpg_vkr.visuals.commands import candidate_entries, visual_request
from rpg_vkr.visuals.context import scene_target


def handle_visual_text(window, text):
    query = visual_request(text)
    if not query:
        return False
    controller = getattr(window, "visuals", None)
    if controller is None:
        window.statusBar().showMessage(
            "Подсистема изображений недоступна; действие героя не выполнено."
        )
        return True
    entries = knowledge_entries(window._session) if window._session.generated_world else ()
    try:
        accepted = False
        if re.search(r"\b(?:сцен|окрестност)", query):
            accepted = controller.request_scene()
        elif re.search(r"\b(?:событи|эпизод)", query):
            events = sorted(
                (e for e in entries if e.category == "events"), key=lambda e: e.last_seen
            )
            if events:
                accepted = controller.request_entry(events[-1])
            elif window._session.turns:
                scene = scene_target(window._session)
                index = len(window._session.turns)
                note = next(
                    (n.text for n in reversed(window._session.narrations) if n.turn_index == index),
                    "",
                )
                scene = replace(
                    scene,
                    entity="turn:" + str(index),
                    subject="turn:" + str(index),
                    title=f"Событие · ход {index}",
                    brief=scene.brief + "\nПубличный рассказ:\n" + note,
                )
                accepted = controller.request(scene)
            else:
                controller.status("В этом мире ещё нет подтверждённого события для изображения.")
        else:
            choices = candidate_entries(entries, query)
            selected = window.chronicles_panel.list.currentItem()
            entry = (
                selected.data(Qt.ItemDataRole.UserRole)
                if selected and window.chronicles_panel.isVisible()
                else None
            )
            if entry not in choices:
                entry = None
            if not entry and len(choices) == 1:
                entry = choices[0]
            if not entry and choices:
                labels = [f"{i + 1}. {e.title}" for i, e in enumerate(choices)]
                answer, ok = QInputDialog.getItem(
                    window, "Что изобразить?", "Выберите известный объект:", labels, 0, False
                )
                if ok:
                    entry = choices[labels.index(answer)]
            if entry:
                accepted = controller.request_entry(entry)
            elif not choices:
                controller.status("Подходящий объект пока не известен герою.")
        if accepted:
            window.action_input.clear()
    except (ValueError, OSError) as error:
        controller.status(str(error))
    return True
