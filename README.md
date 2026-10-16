# DND-NCFU
разработка dnd для выпускной работы для скфу

Учебная текстовая RPG на Python для исследования конфликтных ситуаций.
Целевая машина: Windows x64, Intel i5-1135G7, 16 ГБ RAM.
Обязательные расходы на инструменты и работу приложения: 0 ₽.

## Что уже работает

Первое окно: журнал событий, поле ввода, отправка кнопкой или Enter и небольшой
авторский эпизод у ворот деревни. Команды: **осмотреться**, **поговорить**,
**помочь**, **помощь**. Режим `offline_rules` использует шаблонные ответы,
без нейросети, регистрации и интернета. На неизвестный ввод выдаётся уточнение.

Это прототип этапа 0B: боёв, персонажа, сохранений и ConflictSolver пока нет.
Журнал очищается после закрытия окна. Сцена авторская, материал SRD не импортирован.

## Обновление на Windows

Если вы уже установили этап 0A, откройте PowerShell. Выполняйте команды по одной;
при ошибке остановитесь и сохраните её текст.

```powershell
Set-Location D:\Projects\DND-NCFU
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install --no-cache-dir --require-hashes -r requirements-dev.lock
.\.venv\Scripts\python.exe scripts\check.py
.\.venv\Scripts\python.exe scripts\run_game.py
```

Нужна ветка `setup/development-environment`; текущую ветку показывает
`git branch --show-current`. Не удаляйте свои изменения, если Git отказывается обновляться.
PySide6 Essentials и shiboken6 загружают около 72 МБ на Windows при первой установке.
Полный пакет PySide6 Addons и языковые модели не нужны.

Ожидается **19 passed**, `All checks passed!` и сообщение
`Environment and prototype checks passed`. Это автоматические проверки;
после них отдельно проверьте окно: введите «помочь» и нажмите Enter.
Должен появиться ответ с благодарностью жительницы.

При повторном запуске нужна только команда:

```powershell
.\.venv\Scripts\python.exe scripts\run_game.py
```

Первая установка с нуля: [docs/INSTALL_WINDOWS.md](docs/INSTALL_WINDOWS.md).
Проверка окна без сети: [docs/OFFLINE_TEST.md](docs/OFFLINE_TEST.md).
Активация venv и изменение политики выполнения PowerShell не нужны.

## Карта проекта

- `src/rpg_vkr/ui/main_window.py` — окно; `src/rpg_vkr/narrative/offline.py` — офлайн-сцена.
- `scripts/run_game.py` — запуск; `scripts/check.py` — проверки среды, тестов и Ruff.
- [PROJECT_STATUS.md](PROJECT_STATUS.md) — фактический статус и следующий шаг.
- [AGENTS.md](AGENTS.md) — постоянные инструкции агентам.
- [MASTER_CODEX_RPG_VKR_ZERO_COST.md](MASTER_CODEX_RPG_VKR_ZERO_COST.md) — исходные требования.
- [DECISIONS.md](DECISIONS.md), [RESEARCH_LOG.md](RESEARCH_LOG.md) — решения и исследования.
- [TEST_PLAN.md](TEST_PLAN.md) — проверки и границы их результатов.
- [LICENSES_AND_ATTRIBUTIONS.md](LICENSES_AND_ATTRIBUTIONS.md) — лицензии и SRD.
- [docs/PROJECT_SKILLS.md](docs/PROJECT_SKILLS.md) — три предложения Skills, пока не установлены.
- `docs/originals/` — неизменённые вложения и SHA-256 для проверки их сохранности.

Будущие `local_llm` и `cloud_free` — дополнительные варианты после отдельной проверки.
Будущий `ConflictSolver` рассчитывает решения кодом; рассказчик описывает результат.
Любое изменение игрового состояния будет проходить валидатор.
