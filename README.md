# DND-NCFU
разработка dnd для выпускной работы для скфу

Учебная текстовая RPG на Python для исследования конфликтных ситуаций.
Целевая машина: Windows x64, Intel i5-1135G7, 16 ГБ RAM.
Обязательные расходы на инструменты и работу будущей игры: 0 ₽.

Сейчас подготовлена **среда разработки**, игровой код ещё не создан.
`pytest` проверяет среду и SQLite, `Ruff` проверяет качество Python-кода.
Подписки, API-ключи и серверы для этих проверок не нужны.

## Начало работы на Windows

Полная инструкция: [docs/INSTALL_WINDOWS.md](docs/INSTALL_WINDOWS.md).
Если папка проекта находится в `D:\Projects\DND-NCFU`, откройте PowerShell:

```powershell
Set-Location D:\Projects\DND-NCFU
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
.\.venv\Scripts\python.exe scripts\check.py
```

После установки повторять нужно только последнюю команду. Ожидается `3 passed`,
`All checks passed!` и сообщение `Environment checks passed`.
Окно игры на этом этапе не появляется. Активация venv и изменение политики
выполнения PowerShell не нужны.

## Карта проекта

- [PROJECT_STATUS.md](PROJECT_STATUS.md) — что действительно готово и что дальше.
- [AGENTS.md](AGENTS.md) — постоянные инструкции агентам.
- [MASTER_CODEX_RPG_VKR_ZERO_COST.md](MASTER_CODEX_RPG_VKR_ZERO_COST.md) — исходные требования.
- [DECISIONS.md](DECISIONS.md) — решения, причины и открытые вопросы.
- [RESEARCH_LOG.md](RESEARCH_LOG.md) — проверка источников и исследования.
- [TEST_PLAN.md](TEST_PLAN.md) — проверки и границы их результатов.
- [LICENSES_AND_ATTRIBUTIONS.md](LICENSES_AND_ATTRIBUTIONS.md) — лицензии и SRD.
- [docs/PROJECT_SKILLS.md](docs/PROJECT_SKILLS.md) — три предложения проектных Skills.
- `docs/originals/` — неизменённые вложения и SHA-256 для проверки их сохранности.

Базовый будущий рассказчик `offline_rules` работает по правилам и шаблонам.
`local_llm` и `cloud_free` — дополнительные варианты после отдельной проверки.
`ConflictSolver` рассчитывает решения кодом; рассказчик лишь описывает результат.
Любое изменение состояния проходит валидатор.
