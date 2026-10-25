"""Campaign skill drafts: preview, cancel and one atomic commit."""

import uuid

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QPushButton

from rpg_vkr.domain.d20_progression import SKILLS, rank_limit, required_xp
from rpg_vkr.domain.skill_allocation import preview


def install(window, layout):
    window.skills_group = QGroupBox("Навыки · D20")
    window._skill_draft = {}
    window._skill_draft_base = None
    window._skill_draft_session = None
    form = QFormLayout(window.skills_group)
    window.skills_status = QLabel()
    window.skills_status.setWordWrap(True)
    window.skill_choice = QComboBox()
    for key, (name, _) in SKILLS.items():
        window.skill_choice.addItem(name, key)
    window.skill_details = QLabel()
    window.skill_details.setWordWrap(True)
    window.skill_preview = QLabel()
    window.skill_preview.setWordWrap(True)
    window.train_skill_button = QPushButton("+ Добавить ранг в черновик")
    window.skill_remove_button = QPushButton("− Убрать ранг из черновика")
    window.skill_apply_button = QPushButton("Подтвердить распределение")
    window.skill_cancel_button = QPushButton("Отменить черновик")
    window.train_skill_button.clicked.connect(lambda: train(window))
    window.skill_remove_button.clicked.connect(lambda: remove(window))
    window.skill_apply_button.clicked.connect(lambda: apply(window))
    window.skill_cancel_button.clicked.connect(lambda: cancel(window))
    window.skill_choice.currentIndexChanged.connect(lambda: refresh(window))
    form.addRow(window.skills_status)
    form.addRow("Навык", window.skill_choice)
    form.addRow(window.skill_details)
    form.addRow(window.skill_preview)
    for button in (
        window.train_skill_button,
        window.skill_remove_button,
        window.skill_apply_button,
        window.skill_cancel_button,
    ):
        form.addRow(button)
    layout.addWidget(window.skills_group)


def refresh(window):
    if not hasattr(window, "skills_group"):
        return
    progress = window._session.d20_progress
    window.skills_group.setVisible(progress is not None)
    if progress is None:
        return
    stale = window._skill_draft_base is not None and (
        window._skill_draft_base != progress or window._skill_draft_session is not window._session
    )
    draft = (
        preview(progress, window._skill_draft) if window._skill_draft and not stale else progress
    )
    next_level = str(required_xp(progress.level + 1)) if progress.level < 20 else "предел"
    window.skills_status.setText(
        f"Уровень D20: {progress.level} · XP: {progress.xp} / {next_level}\n"
        f"Очки: {progress.skill_points}; после подтверждения: {draft.skill_points}.\n"
        + (
            "Состояние изменилось: отмените черновик."
            if stale
            else "Черновик действует только после подтверждения."
        )
    )
    skill = window.skill_choice.currentData()
    rank = draft.rank(skill)
    window.skill_details.setText(
        f"Ранг {progress.rank(skill)} → {rank}/5 · бонус +{draft.bonus(skill)} · "
        f"следующее повышение стоит {rank + 1} очк.\n"
        f"Доступный ранг на этом уровне: {rank_limit(progress.level)}."
    )
    available = not window._session.combat.active and window._session.world.hp > 0
    window.train_skill_button.setEnabled(
        available
        and not stale
        and rank < rank_limit(progress.level)
        and draft.skill_points >= rank + 1
    )
    window.skill_remove_button.setEnabled(bool(window._skill_draft.get(skill)) and not stale)
    window.skill_apply_button.setEnabled(bool(window._skill_draft) and not stale and available)
    window.skill_cancel_button.setEnabled(bool(window._skill_draft))
    window.skill_preview.setText(
        "Черновик:\n"
        + "\n".join(
            f"{SKILLS[key][0]}: {progress.rank(key)} → {draft.rank(key)}"
            for key in sorted(window._skill_draft)
        )
        if window._skill_draft and not stale
        else "Черновик устарел."
        if stale
        else "Черновик пуст."
    )


def train(window):
    if window._skill_draft_base is None:
        window._skill_draft_base = window._session.d20_progress
        window._skill_draft_session = window._session
        window._skill_draft_command = uuid.uuid4().hex
    if (
        window._skill_draft_base != window._session.d20_progress
        or window._skill_draft_session is not window._session
    ):
        refresh(window)
        return
    skill = window.skill_choice.currentData()
    increments = dict(window._skill_draft)
    increments[skill] = increments.get(skill, 0) + 1
    try:
        preview(window._skill_draft_base, increments)
    except ValueError as error:
        window.skill_details.setText(str(error))
        return
    window._skill_draft = increments
    refresh(window)


def remove(window):
    skill = window.skill_choice.currentData()
    if window._skill_draft.get(skill):
        window._skill_draft[skill] -= 1
        if not window._skill_draft[skill]:
            del window._skill_draft[skill]
    if not window._skill_draft:
        window._skill_draft_base = None
    refresh(window)


def cancel(window):
    window._skill_draft = {}
    window._skill_draft_base = None
    window._skill_draft_session = None
    refresh(window)


def apply(window):
    if window._skill_draft_session is not window._session:
        refresh(window)
        return
    try:
        window._session.commit_skill_allocation(
            window._skill_draft, window._skill_draft_command, window._skill_draft_base
        )
    except ValueError as error:
        window.skill_details.setText(str(error))
        return
    cancel(window)
    window._dirty = True
    window._refresh_character()
