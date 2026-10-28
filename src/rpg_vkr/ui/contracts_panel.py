"""Player-facing work and faction controls; every button delegates to Session."""

from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QPushButton, QSpinBox

from rpg_vkr.domain.contracts import public


def build(window, layout):
    window.quest_group = QGroupBox("Поручения жителей")
    form = QFormLayout(window.quest_group)
    window.quest_choice = QComboBox()
    form.addRow("Поручение", window.quest_choice)
    window.quest_details = QLabel()
    window.quest_details.setWordWrap(True)
    form.addRow(window.quest_details)
    window.quest_buttons = {}
    from rpg_vkr.ui.unified_panel import run

    for op, label in (
        ("accept", "Принять"),
        ("complete", "Передать добытое"),
        ("cancel", "Отменить поручение"),
    ):
        b = QPushButton(label)
        form.addRow(b)
        window.quest_buttons[op] = b
        b.clicked.connect(
            lambda checked=False, op=op: run(
                window,
                "contract",
                {"operation": op, "offer": (window.quest_choice.currentData() or {}).get("id", "")},
            )
        )
    window.quest_choice.currentIndexChanged.connect(lambda: details(window))
    layout.addRow(window.quest_group)
    window.faction_group = QGroupBox("Объединения")
    form = QFormLayout(window.faction_group)
    window.faction_choice = QComboBox()
    form.addRow("Представитель рядом", window.faction_choice)
    for op, label in (("join", "Вступить ·10 медных"), ("leave", "Покинуть объединение")):
        b = QPushButton(label)
        form.addRow(b)
        b.clicked.connect(
            lambda checked=False, op=op: run(
                window, "faction", {"operation": op, "faction": window.faction_choice.currentData()}
            )
        )
    window.faction_donation = QSpinBox()
    window.faction_donation.setRange(1, 1000)
    form.addRow("Взнос в казну", window.faction_donation)
    b = QPushButton("Передать взнос")
    form.addRow(b)
    b.clicked.connect(
        lambda: run(
            window,
            "faction",
            {
                "operation": "donate",
                "faction": window.faction_choice.currentData(),
                "amount": window.faction_donation.value(),
            },
        )
    )
    layout.addRow(window.faction_group)


def details(window):
    q = window.quest_choice.currentData() or {}
    window.quest_details.setText(
        (
            q.get("title", "")
            + f". Награда: {q.get('reward_cp', 0)} медных и {q.get('xp', 0)} XP. "
            "Материал нужно добыть после принятия поручения."
        )
        if q
        else "Нет доступных поручений."
    )
    for op, b in window.quest_buttons.items():
        b.setEnabled(
            bool(q)
            and (
                (op == "accept" and q.get("status") == "offered")
                or (op in ("complete", "cancel") and q.get("status") == "accepted")
            )
        )


def refresh(window):
    s = window._session
    active = bool(
        getattr(s, "is_unified", False)
        and s.gameplay.get("catalog_revision") == 3
        and s.generated_world
    )
    window.quest_group.setVisible(active)
    window.faction_group.setVisible(active)
    if not active:
        return
    old = (window.quest_choice.currentData() or {}).get("id")
    rows = public(s)
    window.quest_choice.blockSignals(True)
    window.quest_choice.clear()
    for row in rows:
        window.quest_choice.addItem(
            row["npc_name"]
            + ": "
            + row["title"]
            + (" · принято" if row["status"] == "accepted" else ""),
            row,
        )
    for i in range(window.quest_choice.count()):
        if window.quest_choice.itemData(i)["id"] == old:
            window.quest_choice.setCurrentIndex(i)
            break
    window.quest_choice.blockSignals(False)
    details(window)
    window.faction_choice.clear()
    for id, f in s.gameplay["known_factions"].items():
        if any(s.actor_is_here(m) for m in s.gameplay["factions_v3"][id]["members"]):
            window.faction_choice.addItem(f["name"] + f" · репутация{f['reputation']}", id)
    window.faction_group.setVisible(window.faction_choice.count() > 0)
