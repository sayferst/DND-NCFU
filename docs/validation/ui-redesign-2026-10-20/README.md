# Проверка визуального пакета 1R

20.10.2026, Linux, Python3.12.14, Qt offscreen. Изменения сделаны отдельными
коммитами: bc4f289 (меню), ac89511 (Хроники), c666879 (Flash), bb3b633 (компактная
вёрстка/приёмка); финальная документация/контраст — следующим коммитом.

## Что подтверждено

- stage1-menu.txt: 53passed/7.71с.
- stage2-accepted.txt: 57passed/15.17с.
- stage3-flash.txt: 76passed/17.59с.
- stage4-layout-release.txt: 48passed/13.47с.
- full-check-final.txt: **1003passed,0failed/skipped,89.79с**, pip/Ruff успешны,
 145Python-файлов. Это итоговая приёмка после всех изменений кода.

В папке сохранены и неуспешные прогоны. stage2-* содержат прежние неверные
ожидания заголовка и исправленную ошибку подготовки удалённого NPC; stage3-first/
second-helper-error — неверно вызванный помощник ожидания в новом тесте,
focused-accepted —18pass после исправления; итог stage3 добавляет проверку
перезапуска и старые RouterAI регрессии. stage4-layout/second — два ошибочных
имени тестового файла (0тестов). stage4-layout-accepted:47pass/1fail из-за
устаревшего светлого цвета врага; full-check-candidate:1002pass/1fail из-за
видимости расчётов при открытии боя из меню. Боевой переход исправлен, цвет
в тесте следует новой тёмной теме, требования RNG/урона/сохранения сохранены.
full-check-release:1003pass, но Ruff format отклонил1файл; это не финальная приёмка.

Ни один тест не является живой оценкой DeepSeek. GET/POST в тестах RouterAI идут
на loopback с вымышленным ключом. Подключение Flash проверяется двумяGET и0POST;
настоящих ключей/платных генераций/пополнений не использовали. Windows DPAPI
на Linux не исполнялся: envelope-тест использует явную подмену шифрования.

## Визуальная проверка

[Меню](screenshots/menu-desktop.png), [маленькое меню](screenshots/menu-compact.png),
[FullHD](screenshots/menu-fullhd.png), [Хроники](screenshots/chronicles-card.png),
[tooltip](screenshots/chronicles-tooltip.png), [компактный вид](screenshots/chronicles-compact.png),
[развёрнутая карточка](screenshots/chronicles-expanded.png),
[приключение](screenshots/adventure-desktop.png), [маленькое окно](screenshots/adventure-compact.png),
[расчёты](screenshots/compact-rolls.png), [настройки](screenshots/settings.png),
[сохранения](screenshots/saves.png), [герой](screenshots/hero.png),
[инвентарь](screenshots/inventory.png), [карта](screenshots/map.png),
[создание](screenshots/character-creation.png), [светлая тема](screenshots/chronicles-light.png).

Это фактические grab() Qt-окон, не макеты. Данные — временная тестовая кампания
из tests/response_cases.py, публичные раскрытия из test_chronicles.learn;
никаких NPC из снимков в постоянный мир пользователя не добавлено. Исходник
съёмки сохранён в capture-source.txt, stderr/размеры в screenshots-qt-log.txt,
SHA-256 PNG — в screenshots-manifest.json. Для повторения скопировать источник
в /tmp/capture-ui.py и из корня выполнить:

```bash
QT_QPA_PLATFORM=offscreen PYTHONPATH=src:tests .venv/bin/python /tmp/capture-ui.py
```

Снимки просмотрены, после них исправлены белая подложка scroll-содержимого,
контраст, вертикальные фильтры, доступ к расчётам и полной карточке на640×620.
Fontconfig/offscreen может сообщать отсутствие cache/raise/size-hints; итог
скрипта успешный, окна сохранены. Это не проверка нативного Windows-дисплея,
масштабирования125–150% или реальной кадровой частоты ноутбука.

## Сохранность исходников и ограничения

immutable-audit.json сравнивает исходные fixtures/data/research/requirements с
предыдущим выпуском d322732 и проверяет, что AGENTS/промпт сохранены как префикс.
Новое ТЗ владельца архивировано побайтово, SHA в RESEARCH_LOG.md. Старые данные,
игровые файлы domain/narrative/application и lockfile не менялись. В промпт
добавлен лишь контракт публичных knowledge-полей для проекции знаний.

Подробные ограничения разметки публичности/старой прозы, DPAPI и тестирования
облака: docs/FANTASY_UI_AND_CHRONICLES.md и KNOWN_ISSUES.md.
