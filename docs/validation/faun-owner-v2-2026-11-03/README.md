# Проверка дополнения v2 — 03.11.2026

Реализация: d2e9b4e (данные), f4554d6 (Windows/GUI), 67b38cd (GPU tools).
SHA проверяемых исполняемых входов: implementation-inputs-01.json.
Ниже перечислены фактические команды и границы свидетельств. Целевые наборы
пересекаются между собой и с полным; числа не складываются.

| Свидетельство | Реальная проверка |
| --- | --- |
| full-check-02.txt / full-outcome-01.json / full-suite-summary-01.json | Полный scripts/check.py exit0:12301 passed,6 skipped,0 failed/errors,13 пакетов/155 файлов; pip check/Ruff check/format418 файлов успешны |
| targeted-134.txt | 134 passed; Excel v2, установка, UI, протокол существующего OllamaClient, коллектор, переносимость GPU tools, resume/holdout; HTTP — тестовый сервер, весов нет |
| ui-excel-35.txt | 35 passed; актуализированные сохранение локального выбора и разметка |
| excel-final-12.txt | 12 passed; в том числе пустые inlineStr после пересохранения, формулы/ID/дубли, архив v1, частичное заполнение и раздельное одобрение |
| xlsx-independent-01.json | openpyxl3.1.5 открыл/пересохранил/импортировал книгу:1000+1000 строк,200/800,40/условие,10/семейство,20 иллюстраций,16 формул. Native Excel recalculation NOT_RUN |
| game-contracts-01.json | Реальное исполнение11 авторских игровых сценариев и save/load; Faun NOT_RUN |
| annotation-proposals-01.json | 800 предложений:480 RULE_LABELED,320 HUMAN_REVIEW_REQUIRED,0 AI,0 human approval,0 SFT |
| gpu-bundle-manifest-01.json | Реально созданный ZIP с whitelist/SHA инструментов; без весов/данных/секретов. Его распаковка и dry-run проверены тестом |
| hardware-cloud-01.json | Только текущий Linux execution_environment; BLOCKED_HARDWARE, не аппаратная проверка Acer |
| train-dry-run-01.json | Фактический preflight BLOCKED_DATA; training_started false |
| local-provider-01.json | Фактическая проверка127.0.0.1:11434 дала BLOCKED_PROVIDER; модели не загружались |
| hf-dataset-audit-v2-01.json | Публичные HF metadata; исходные корпуса не скачаны и не допущены |
| windows-user-evidence-01.json | Обезличенное свидетельство присланного владельцем прежнего Windows-журнала:12280 passed/1 skipped. Текущие изменения/установку Faun этот журнал не проверяет |
| owner-faun-smoke-01.json | Новый присланный владельцем журнал: pull100%/7,5ГБ, verifying SHA-256, success и LOCAL_SMOKE_OK_GAME_EVALUATION_REQUIRED. Реальный локальный запрос пользователя, не запуск агента; игровые ответы/TPS/RAM не предоставлены |

Полная проверка запускается `.venv/bin/python scripts/check.py` с разрешёнными
loopback-соединениями для тестовых серверов. full-check-01.txt был **прерван**
для исправления обнаруженного независимой XLSX-проверкой пустого inlineStr;
успехом всей проверки не считается. full-check-02.txt — успешный повторный полный
запуск после исправления:12301 passed,6 skipped,0 failed/errors. Сумма времени
JUnit-пакетов1075,166с. Пропущены дорогой opt-in маршрут1→20 и5 тестов настоящего
PowerShell updater. Точные имена/причины — full-outcome-01.json; JUnit summary
сохранён, исходные XML остаются в build/check-batches-65cabcbdffa74ae0b82ea3a2a9111871.

Исправленные при целевой проверке проблемы: скрытый локальный пункт современной
UI; ошибка сигнала завершения в новом benchmark (plain narration выдаёт
narration_ready); несовместимость чтения пустых ячеек после пересохранения;
общая привязка ремонтного инструмента как исходного материала. Отдельные неудачные
целевые запуски оставались диагностикой разработки, итоговые свидетельства выше
показывают повторные проверки после исправления. Проверочный holdout в pytest
синтетический и временный; результатом реального обучения он не является.

Облачный агент не запускал нативный Windows installer/GUI или настоящий Faun
inference. Позднее владелец подтвердил pull и короткий inference на своём Acer;
игровое качество и показатели ещё не проверены. GPU batch/обучение/reload/экспорт
не запускались. Реальных шагов оптимизации0,
адаптеров0, платных запросов0, передач приватных кампаний0, загрузок весов агентом0.
GGUF на7,5ГБ скачан владельцем с его подтверждением.
