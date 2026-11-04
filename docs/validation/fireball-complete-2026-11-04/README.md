# Полный доступный FIREBALL — 04.11.2026

Это проверка данных и offline-инструментов; обучение и inference модели не запускались.
Большие оригиналы, B/C, словари и полные очереди проверки находятся вне Git.

- `source-manifest.json`: все 1476 обнаруженных HF entries, статусы метаданных,
  все 1473 исходных файла с размерами/SHA/revision/числом строк, первичные материалы.
- `discovery-recheck.txt`, `tree-comparison.json`, `source-cache-verification.txt`:
  повторная проверка полного дерева и всех 1471 сохранённых Git/LFS hashes;
  1471 CACHED, пропусков/лишних файлов нет.
- `lossless-check.json`: независимая побайтовая и JSON/type-сверка всех
  154196 строк,1473 файлов,0 потерянных полей,0 ошибок,0 quarantine.
- `coverage-summary.json`: восемь задач, все решения с причинами,
  типы/роли/эвристика языка/splits; полная инвентаризация2132полей в приватном комплекте.
- `duplicate-summary.json`, `extended-audit.json`, `readiness-and-leakage.json`:
  полные/нормализованные/приближённые дубли, demo25 против HF, сущности,
  1470компонент (1176/147/147),0межчастных/межгрупповых history-связей.
- `task-integrity-check.json`: отдельный полный аудит каждой записи×задачи,
  допустимого состава input и строгого порядка всех связей истории; все нарушения0.
- `demo-reference-resolution.json`:218ссылок на342доступных raw-demo событий,
  в том числе12after-ссылок author_bot=False; DM и человеческое авторство текста
  автоматически не устанавливаются. Полный raw по ним не восстанавливается.
- `native-tokenization-summary.json`:606269представлений,1206068534токена,
  240528171target-токен, максимум38276; распределения/профили/маски/ChatML.
  Длинные targets сохраняются целиком; профили не являются GPU fit-тестом.
- `native-tokenizer-parity.json`: независимая сверка с AutoTokenizer на288native
  случаях среди завершённых на момент проверки и5пограничных форматах.
  Полный проход всех606269 выполнен точным pinned backend; второй полный
  проход AutoTokenizer не заявляется.
- `native-export-verification.json`:9473shards/606269строк полностью
  реконструированы и сверены с C по messages/source/targets/длинам/маскам/hashes.
  Потерь/дублей/расхождений0. После уточнения связей demo исправлены только
  split-метки310ранее записанных строк в292shards; targets/tokens не изменялись.
  Полный журнал исправлений сохранён с корпусом вне Git.
- `raw-access-probes.json`:официальный полный raw URL вернул403 наHEAD иGETRange
  из данной среды. Это ограничение доступности, а не утверждение о глобальном
  отсутствии архива; все доступные filtered-данные обработаны.
- `targeted-final-72.txt`: **72passed/5.68с**,21новая регрессия и прежние тесты
  training/tokenizer/transfer. Числа не складываются с прошлыми прогонами.

Точная команда целевого прогона:

```text
.venv/bin/python -m pytest tests/test_fireball_observations.py tests/test_fireball.py tests/test_training_tokenization.py tests/test_faun_tokenizer_fetch.py tests/test_faun_transfer.py tests/test_training_pipeline.py tests/test_training_story_contract.py tests/test_training_pack_review.py -q
```

Ruff check/format457файлов успешны. Полный игровой12405-набор заново не
запускался. Новый Windows/GUI, GPU batch, обучение, оценка художественного
качества и runtime-реализация Avrae не проверялись. human_approved/train_admitted0;
отсутствие явных contact-patterns не названо человеческим privacy approval.

Команды и атрибуция: [FIREBALL_COMPLETE.md](../../intelligent_gm/FIREBALL_COMPLETE.md).

Итоговая доставка: `delivery-checksums.json`. Проверены SHA/размер/CRC всех120
payload файлов B/C-ZIP и всех1473исходников+102первичных материалов source-ZIP.
Проверен отдельный portable-import tools без модели/Torch; SQLite quick_check=ok,
WAL checkpoint0/0/0. Архивы вне Git, byte-bound code commit0cb45f3.
