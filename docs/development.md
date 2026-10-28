# Разработка

Рабочая база: `feature/unified-rpg-automatic-gm`; ветка оформления:
`docs/repository-presentation`. main пока содержит только начальный коммит.
Не переключайте сборщик на main до согласованной интеграции и проверки.

Windows x64, Python 3.12, Git. Из корня checkout:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev.lock
.\.venv\Scripts\python.exe scripts\check.py
.\.venv\Scripts\python.exe scripts\run_game.py
```

Сначала прочитайте [AGENTS](../AGENTS.md), статус и журналы проекта.
Проверяйте изменение целевыми тестами; перед выпуском нужен полный Windows CI.
Не меняйте старые fixtures ради прохождения тестов. Схема сохранения требует
читателя прежних форматов, реальной fixture и проверки продолжения RNG.

Архитектура: UI → Session/валидаторы → правила → JSON/SQLite. Мастер не пишет
состояние напрямую. RAG и отдельный training-контур не подменяют механику.
Тесты используют временные каталоги и локальные/поддельные транспорты.
Платные API и обучение не запускаются обычными проверками.

После интеграции: короткая feature/fix/docs-ветка → PR → обязательные проверки → main.
Сейчас эту схему только готовим. Не создавайте develop без причины.
Сборки: [инструкция владельцу](owner-guide.md). Порядок вклада: [CONTRIBUTING](../CONTRIBUTING.md).
