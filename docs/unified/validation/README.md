# Фактические проверки единого потока, 26–27.10.2026

Исходный checkout468f774; среда Linux/Python3.12, Qt offscreen. Новые сетевые
тесты используют только127.0.0.1. Платных запросов/обучения нет.

baseline-01.txt — scripts/check.py до изменений:1851passed.
Полные логи сохраняются под разными именами, в том числе неуспешные:

- rules-01…03: исправлены неверное ожидание начального календаря и реальный
  eager-default KeyError нового типа в storage/catalog;03успешен.
- integration-01/02,world-ui-01/02: прерваны при устаревших модальных сценариях
  старого конструктора. Эти файлы не считаются полными успешными прогонами.
- integration-03:222passed/1failed, устаревшее ожидание RAG-kind.
- world-first-01/world-ui-03/start-first-01: устаревшие ожидания ручного старта
  мира заменены проверкой автоматического старта; повторы сохранены отдельно.
- rules-04: реальные dice receipt не содержали index; исправлено.
- rules-05/06: уточнены реальные ownership/stack исходного товара;
  реализовано отделение единицы с сохранением остатка и владельца.
- data-01:15passed/1failed, тест проверял legacy-window вместо современной
  DeveloperConsole; исправлена постановка, а не возвращена удалённая вкладка.
- full-tests-01:1874passed/1failed, оставшееся старое ожидание ручного старта.
- full-check-03:1877passed/319.28с; full-check-04:1879passed/328.58с;
  full-check-05:1879passed/327.65с; full-check-06:1879passed/314.09с.
- font-layout-final-01:6passed после наследования шрифта конструктора.
- rules-07: исправленная реальная продажа/расход физического source;
  повторная продажа/расход и buy-sell-rebuy с replay, без двойных экземпляров.
- full-check-07 — окончательный полный прогон после этого исправления:
  **1880passed/302.93с**,pip/Ruffcheck/format327файлов успешны.
- canonical-checks-01:59passed/3socketerrors из-за запрещённого loopback;
  canonical-checks-02:63passed/2.63с с разрешённым loopback и добавленнымUIcase.
  Новые задачи/DC используют одну математику,без старых рангов;чистая проверка
  характеристики не получает незаслуженную классовую подготовку.
- full-check-08:1882passed/301.50с,затемRuffE501наоднойстрокеprompt.
  Разделены только соседние литералы,текстpromptне меняется. Ruffповторно
  успешен. full-check-09 — итоговыйполныйповтор после форматирования:
  **1882passed/288.86с**,pip/Ruffcheck/format327файлов успешны,exit0.
- linux-build-03 — успешная финальная сборка;linux-self-check-03/
  linux-smoke-04успешны,external_model_requests=0. packaging-audit-02
  подтверждаетindex и отсутствиеtraining/Torch/raw/weights в payload.

target-final-01…06 — целевые регрессии соответствующих изменений; полные
итоговые команды/результат перечислены в ../acceptance_report.md.

linux-build-01 и linux-self-check-01 — первая рабочая PyInstaller-сборка.
linux-smoke-01 завершился PermissionError: песочница запретила loopback socket.
linux-smoke-02 с разрешённым loopback успешен: реальный конструктор, автоматическая
генерация мира на HTTP fixture, JSON/SQLite/RNG,0внешних запросов модели.
linux-build-02 и последующие packaged reports относятся к финальному коду.
Сборка имеет provenance468f774-modified: она создана до финального commit.
Это Linux bundle, не проверка Windows EXE/DPAPI/Setup.

source-inspection-01/dataset-dry-01/corpus-audit-01 — исходный19-file ZIP,
SHA/19000canonical/200aliases,0SFT-пар. Raw и SQLite не включены в Git.
training-preflight-01: BLOCKED_DATA, training_started=false.
base-model-metadata-01 содержит только публичные metadata,не веса.
evaluation-library-01 — локальная подготовка developer SQLite для benchmark.
offline-evaluation-01 —100сценариев×4mockусловия,не оценка качества модели.
В нём сохранено старое имя training=BLOCKED_PROVIDER_TRAINING от legacybenchmark;
wrapper исправлен на NOT_RUN_BY_THIS_COMMAND,новый CLIотчёт02. Автоматические
embeddedметоды присутствуют во всех условиях,benchmarkне изолирует их эффект.
evaluation-final-01:целевые тесты/повтор после уточнения только метаданных отчёта.
Первая попытка evaluation без developer library остановилась до создания
отчёта с FileNotFoundError; после явного CLI ingest выполнен новый запуск.

Скриншоты ../screenshots — настоящие Qt widgets финального конструктора
и DeveloperConsole, свежая временная data-dir, без ключей и частных кампаний.
Ручной визуальный просмотр выполнен в Linux. Нативный Windows/DPI остаётся
отдельной непроведённой приёмкой; исторические Windows-свидетельства не заменяют её.

Итог27.10.2026:immutable-audit-02 —86protected+AGENTSнеизменны;
changed-code-manifest-02 фиксирует62изменённыхsource/config/dataфайла;
secret-scan-02не нашёл ключей в изменённых/новых текстах. Modelweights/rawне
добавлены вGit. После full-check-09 менялась только документация.
