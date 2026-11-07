# Проверка учебного v3 — 03.11.2026

Реально выполнено на Linux/Python3.12; игровой runtime не зависит от training-stack.

- `audit-summary.json`: только обезличенные счётчики и SHA. Настоящий Excel
  импортирован,274 недостающие связи исправлены в новой копии,644 случая
  остались с недостающими фактами. В Git нет исходного архива/ответов/QA-логов.
- `tokenizer-parity.json`: все40 примеров дали одинаковые ID и loss-маски
  в tokenizer.json backend и настоящем AutoTokenizer Transformers5.3.0.
  Повторено в отдельной среде из CPU hash-lock безTorch;29 пакетов совместимы.
- `portable-check.json`: hash-manifest ZIP проверен; tool/data layout
  извлечён в новую папку. Отчёт токенизации совпал целиком. Dry-run ожидаемо
  BLOCKED_MODEL — исходные Safetensors не скачивались.
- `targeted-78.txt`:78passed/25.48с,11 файлов. Тесты используют авторские
  fixtures и loopback HTTP, не настоящую Faun/CUDA.
- `full-check-01.txt` и `full-suite-summary.json`: scripts/check.py exit0;
  12346passed/6skipped/0failed/errors,14пакетов160файлов; pip/Ruff430 успешны.
  Skips: opt-in дорогой1→20 replay и5 Windows/PowerShell updater-тестов.

Предыдущий targeted-03 выявил ошибку тестового `/api/tags` fixture
(не был указан обязательный size), исправленную до успешного полного прогона;
два loopback-теста также запускались без network permission и получили EPERM.
Успешный targeted-04/полный прогон выполнялись с разрешённой сетью sandbox.
Прежние raw-отчёты сохранены вне Git, не перезаписаны.

Архив пользователя дал0 в gm-sft-v1. Отдельный редакторский синтетический
пилот40/32–4–4 не является реальными эпизодами, человеческими оценками
или доказательством качества мастера. Сохраняются исходные пары и связь
редакторского ответа с ними; синтетическое происхождение не скрывается.

GPU stack, исходная12B база, optimizer step, реальный checkpoint resume,
адаптерный inference, новая Windows GUI и литературное A/B NOT_RUN.
Реальных шагов оптимизации0, платных действий0, расходы0₽.
