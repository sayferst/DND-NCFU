"""Start the real launcher from a different directory and run the Qt event loop."""

import os
import subprocess
import sys
from pathlib import Path


def test_launcher_process_handles_action_and_exits(tmp_path):
    launcher = Path(__file__).resolve().parents[1] / "scripts" / "run_game.py"
    # A separate process exercises the actual entry point, event loop and exit code.
    probe = """
import runpy
import sys
import traceback
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMainWindow

app = QApplication([])
def interact():
    try:
        windows = [w for w in app.topLevelWidgets() if isinstance(w, QMainWindow)]
        assert len(windows) == 1
        window = windows[0]
        assert window.isVisible()
        assert window.tabs.tabText(window.tabs.currentIndex()) == "Главное меню"
        window.resume_button.click()
        if sys.argv[2] == 'save':
            window.font_size.setValue(16)
            window.theme_choice.setCurrentText('Тёмная')
            window.action_input.setText('помочь')
            QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            window.action_input.setText('бросить d20')
            QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            window.action_input.setText('проверить силу')
            QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            for command in ['взять поручение', 'идти на дорогу', 'исследовать дорогу',
                            'идти на рынок', 'доставить корзину', 'подойти к торговцу',
                            'купить бинт',
                            'использовать бинт']:
                window.action_input.setText(command)
                QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            window.save_slot(1)
        else:
            assert window.font_size.value() == 16
            assert window.journal.font().pointSize() == 16
            assert window.theme_choice.currentText() == 'Тёмная'
            window.load_slot(1)
            assert 'Жительница благодарит' in window.journal.toPlainText()
            assert 'Кубик: На кубике выпало ' in window.journal.toPlainText()
            assert window.resolution_panel.isVisible()
            assert 'Итого:' in window.roll_breakdown.toPlainText()
            assert len(window._session.turns) == 11
            assert window._session.world.quest == 'completed'
            assert window._session.world.hp == 12
            assert window._session.world.gold in (12, 14)
            assert window._session.world.shop_stock == 2
            assert 'Сила: 14 (+2)' == window.ability_labels['strength'].text()
            window.action_input.setText('бросить d20')
            QTest.keyClick(window.action_input, Qt.Key.Key_Return)
            assert window._session.turns[-1].roll.index == 4
            window.save_slot(2)
        print('Launcher interaction verified', flush=True)
        window.close()
    except Exception:
        traceback.print_exc()
        app.exit(1)

QTimer.singleShot(0, interact)
QTimer.singleShot(10000, lambda: app.exit(2))
runpy.run_path(sys.argv[1], run_name='__main__')
"""
    environment = os.environ.copy()
    environment["RPG_VKR_DATA_DIR"] = str(tmp_path / "user-data")
    for phase in ("save", "load"):
        result = subprocess.run(
            [sys.executable, "-c", probe, str(launcher), phase],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Launcher interaction verified" in result.stdout


def test_real_creator_modal_progression_and_restart(tmp_path):
    launcher = Path(__file__).resolve().parents[1] / "scripts" / "run_game.py"
    probe = """
import runpy
import sys
import traceback
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow
app = QApplication([])

def fill_creator():
    try:
        from rpg_vkr.ui.creation_dialog import CreationDialog
        dialog = app.activeModalWidget()
        assert isinstance(dialog, CreationDialog)
        dialog.name_input.setText('Мира')
        dialog.class_choice.setCurrentIndex(0)
        dialog.apply_recommended()
        dialog.accept()
    except Exception:
        traceback.print_exc()
        if app.activeModalWidget():
            app.activeModalWidget().reject()
        app.exit(1)

def interact():
    try:
        window = next(w for w in app.topLevelWidgets() if isinstance(w, QMainWindow))
        if sys.argv[2] == 'create':
            QTimer.singleShot(0, fill_creator)
            window.new_character()
            assert window._session.character.name == 'Мира'
            assert window._session.progress.enabled
            assert not window.edit_character_button.isEnabled()
            window.cart_button.click()
            window.study_button.click()
            window._run_command('идти на дорогу')
            window.quick_buttons['исследовать дорогу'].click()
            assert window._session.progress.level == 2
            assert len(window._session.progress.events) == 3
            assert window._session.world.max_hp == 14
            window.save_slot(1)
        else:
            window.load_slot(1)
            assert window._session.character.name == 'Мира'
            assert window._session.progress.level == 2
            assert window._session.world.max_hp == 14
            assert len(window._session.progress.events) == 3
            assert 'Мира' in window.resource_label.text()
            assert 'уровень 2' in window.progress_label.text()
            assert 'Учебный меч' in window.inventory_label.text()
            assert 'Развитие:' in window.journal.toPlainText()
            assert not window.study_button.isEnabled()
            xp = window._session.progress.xp
            window._run_command('изучить учебник')
            assert window._session.progress.xp == xp
            window._run_command('бросить d20')
            assert window._session.turns[-1].roll.index == 3
            window.save_slot(2)
        print('Created hero restart verified', flush=True)
        window.close()
    except Exception:
        traceback.print_exc()
        app.exit(1)

QTimer.singleShot(0, interact)
QTimer.singleShot(10000, lambda: app.exit(2))
runpy.run_path(sys.argv[1], run_name='__main__')
"""
    environment = os.environ.copy()
    environment["RPG_VKR_DATA_DIR"] = str(tmp_path / "created-data")
    for phase in ("create", "restore"):
        result = subprocess.run(
            [sys.executable, "-c", probe, str(launcher), phase],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Created hero restart verified" in result.stdout


def test_real_combat_save_restart_and_multi_roll_continuation(tmp_path):
    launcher = Path(__file__).resolve().parents[1] / "scripts" / "run_game.py"
    probe = """
import runpy
import sys
import traceback
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow
app = QApplication([])
def interact():
    try:
        from rpg_vkr.application import Session
        from rpg_vkr.domain.character import ABILITY_NAMES, Character
        from rpg_vkr.domain.progression import ARCHETYPES
        window = next(w for w in app.topLevelWidgets() if isinstance(w, QMainWindow))
        if sys.argv[2] == 'fight':
            character = Character(name='Мира', **dict(zip(ABILITY_NAMES,
                                  ARCHETYPES['fighter'].scores, strict=True)))
            window._session = Session.create_hero(character, 'fighter', seed=5)
            window._refresh_character()
            window._render_journal()
            window._run_command('изучить учебник')
            window._run_command('идти на дорогу')
            window.open_section('Схватка')
            assert window.combat_targets.currentData() == 'wolf'
            window.combat_stealth.click()
            assert window._session.combat.surprise
            assert window.resolution_panel.isVisible()
            assert '20 + 1 = 21' in window.roll_breakdown.toPlainText()
            from rpg_vkr.narrative.context import build_frame
            from rpg_vkr.narrative.records import Narration
            frame = build_frame(window._session)
            window._session.add_narration(Narration(3, 'local-test:1',
                'Вы приближаетесь к волку незамеченным.', frame.fingerprint))
            window._render_journal()
            assert len(window._session.memory.events) == 3
            window.save_slot(1)
        else:
            window.load_slot(1)
            assert window._session.combat.surprise
            assert len(window._session.memory.events) == 3
            assert 'Вы приближаетесь к волку незамеченным.' in window.journal.toPlainText()
            assert not window.enable_local_narrator.isChecked()
            assert not window.ollama.busy
            assert window.journal.actor_colour('wolf').name() == '#b00020'
            window.open_section('Схватка')
            window.combat_attack.click()
            assert window._session.combat.actor('wolf').hp == 0
            assert 'Скрытая атака ×2 · урон 16' in window.journal.toPlainText()
            assert '=' not in window.journal.toPlainText()
            assert '(6 + 2) × 2 = 16' in window.roll_breakdown.toPlainText()
            assert window._session.progress.level == 2
            assert window._session.world.hp == 12
            assert window._session.world.max_hp == 14
            assert 'Бросков в сессии: 3' in window.roll_summary.text()
            assert window.journal.font().bold()
            assert window.journal.font().pointSize() == 13
            window._run_command('бросить d20')
            assert window._session.turns[-1].roll.value == 17
            window.save_slot(2)
        print('Combat restart verified', flush=True)
        window.close()
    except Exception:
        traceback.print_exc()
        app.exit(1)
QTimer.singleShot(0, interact)
QTimer.singleShot(10000, lambda: app.exit(2))
runpy.run_path(sys.argv[1], run_name='__main__')
"""
    environment = os.environ.copy()
    environment["RPG_VKR_DATA_DIR"] = str(tmp_path / "combat-data")
    for phase in ("fight", "restore"):
        result = subprocess.run(
            [sys.executable, "-c", probe, str(launcher), phase],
            cwd=tmp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Combat restart verified" in result.stdout
