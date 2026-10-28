# Итоговые свидетельства 0.4.0

Действующий runtime: **fb7594ac2dadd03c0fc0cabde7fd6f0093d3ea0f**.
Игровые правила соответствуют e3c536f и локальному checkpoint8cf1228.
fb7594a добавляет фоновую загрузку через SQLite-кнопку и интеграционный тест.
Пять дополнительных сырых логов не включены в опубликованный коммит;
полная локальная recovery-копия сохранена.

[Итог исполнения](../../completion/FINAL_EXECUTION.md) ·
[Матрица критериев](../../completion/ACCEPTANCE_MATRIX.md) ·
[Машинный сводный результат и SHA входов](FINAL_VALIDATION.json).

| Проверка | Свидетельство |
|---|---|
| Полный Linux,12203passed/5skipped | [summary](linux-final-ui-summary-01.json) |
| Все3360ID на новой политике мира4 | [execution proof](catalog3-policy4-proof-01.json), [категории/школы](catalog3-policy4-audit-01.json) |
| Пять классов1→20 | [Воин](policy4-warrior-01.json), [Лучник](policy4-archer-01.json), [Плут](policy4-rogue-01.json), [Маг](policy4-mage-01.json), [Жрец](policy4-cleric-01.json) |
| Ремесленник | [Чистая работа до11](policy4-scarce-artisan-01.json), [попытка чистой работы до20](policy4-scarce-artisan-02.json), [смешанный маршрут](policy4-artisan-combined-01.json) |
| Windows12207passed/1skipped | [summary](native-fb-summary.json), [все задания CI](https://github.com/sayferst/DND-NCFU/actions/runs/40704957897) |
| Настоящий Setup0.3.1→0.4.0, повторное обновление | [setup-result](native-fb-setup-result.json), [первое чтение старой кампании EXE](native-fb-first-installed-save-load.json), [повторное чтение](native-fb-repeat-update-installed-save-load.json) |
| Проверка скачанного Windows-артефакта | [CRC, SHA ZIP и каждого файла](native-fb-artifact-proof.json) |
| Frozen оригиналы и старый capture | [86хэшей](immutable-policy4-01.json), [побайтовое совпадение488пар](capture-replay-compatibility-01.json) |
| Реальный DeepSeek,500ходов/600ответов | [прогон и ограничения](deepseek-long-500-01.json), [600usage/hash/status](deepseek-usage600-01.json) |
| Исправленная стоимость | [сверка627ответов и исходного резерва](budget-reconciliation-01.json), [бесплатные метаданные ключа](budget-key-metadata-01.json) |
| Нулевой допуск к обучению | [live admission](live-candidates-admission-01.json), [preflight](training-preflight-01.json) |

Сценарии классов авторские и автоматические: обычный старт200CP, конечные
NPC-кошельки/ресурсы, настоящие публичные команды и валидированные противники.
XP/HP/склады после genesis не подменяются. Смешанный ремесленник продолжает
подлинное сохранение чистой работы, исходный SHA записан в результате.
Контролируемое исполнение каталога не считается прохождением этих кампаний.

Сырые stdout/JUnit, первые неудачные попытки и не опубликованные дополнительные
логи сохранены отдельно в рабочей среде под прежними именами; не перезаписаны.
Первый полный запуск в ограниченном sandbox упал на17операциях loopback socket
с PermissionError; повтор с разрешённой тестовой сетью прошёл полный набор.
Это не платные обращения к модели. Старые full-01 и Windows-падения до
исправлений также не выданы за успешные результаты.

Большие реальные тексты/контексты модели, сырые SFT-кандидаты, предоставленный
10kJSONL, приватные метаданные кабинета и ключ не публикуются и не входят в Setup.
488пар остаютсяpending/rights unknown: обучение0шагов,0адаптеров,0весов.

Windows-артефакт12824514909 доступен до11.11.2026 по текущей политике CI.
CI-проверки не заменяют ручную приёмку монитора/ПК владельца, слепую оценку
двумя людьми и литературную/балансовую проверку всего каталога.
