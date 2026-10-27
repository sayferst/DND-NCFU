# Отдельный контур данных и обучения

Не является зависимостью Windows-игры. По умолчанию никакой тренировки,
скачивания модели, платного API или фонового GPU-задания нет.
Из корня checkout, Python3.12:

```powershell
.\.venv\Scripts\python.exe -m training.inspect_archive --input "ПУТЬ_К_АРХИВУ.zip" --report "НОВЫЙ_ОТЧЕТ.json"
.\.venv\Scripts\python.exe -m training.prepare_dataset --input "ПУТЬ_К_АРХИВУ.zip" --output "data/processed/gm-sft-v1" --dry-run
.\.venv\Scripts\python.exe -m training.build_embedded_knowledge --output data/approved_knowledge
.\.venv\Scripts\python.exe -m training.train_lora --config training/configs/one_qlora_config.json --dry-run
```

Приложенный CODEX_READY действительно проверен:19файлов,19000канонических
структурных записей,200старых alias. Они не равны19000SFT-парам. Реальных
одобренных пар с контекстом/engine_receipt/ответом нет:preflight BLOCKED_DATA.
Результаты: docs/unified/validation/corpus-audit-01.json, dataset-dry-01.json.
Ни одной тренировки/градиентного шага/adapter_model.safetensors в этом задании нет.
GPU/NVIDIA в рабочей Linux-среде отсутствует; компьютер владельца не инспектировался.

inspect_archive читает ZIP/tar/MD/TXT/JSON/JSONL; SQLite read-only поддерживает
явный экспорт gm_samples(payload TEXT),не произвольные схемы БД.7z сейчас
отклоняется:безопасный backend не установлен. Никакого extractall на диск/SQL из
файла/запуска вложенных скриптов. Поддержка произвольных chat-экспортов не
подменяет отсутствующий runtime-контекст: неоднозначные записи не допускаются.

prepare_dataset без --dry-run требует --confirm-privacy-review и новую
папку назначения. Это подтверждение владельца после проверки,не флаг игрока.
Схема gm-sft-v1, права permitted,review approved,реальная engine_receipt;
synthetic fixture отклоняется. Кампании и найденные near-дубли объединяются
перед train/val/test. Консервативный фильтр не доказывает художественное качество.
Ручной выборочный аудит и происхождение реальных receipt остаются обязательными.

build_embedded_knowledge по умолчанию воспроизводит24оригинальных метода.
--input указывает подготовленную папку; только train-примеры с явным
approved_for_public_knowledge=true,подходящим knowledge_type,правами/ревью
могут стать небольшими публичными выдержками. Частные факты не публикуются.
Лимит компактного артефакта240КиБ. При изменении данных используйте новый
каталог версии для сборки; существующий отличный index не перезаписывается.
Игрок ничего не импортирует: установщик содержит готовый index.json.

Для реальной QLoRA нужен отдельный Linux/WSL2 NVIDIA-контур, локально полученные
разрешённые веса по проверенной revision и проверенный датасет. requirements-train.txt
не устанавливается клиенту. Конфигурация JSON вместо YAML избегает лишней
runtime-зависимости; Qwen/Qwen3-4B,revision/license подтверждены метаданными
HuggingFace, веса не скачивались. Наличие конфигурации не доказывает совместимость
оборудования или успешную тренировку. Используется NF4/BF16: нужен совместимый GPU.

train_lora --smoke-test выполняет2реальных шага только после prerequisites;
обычный запуск — реальный Transformers Trainer + PEFT. Loss только по ответу,
prompt tokens=-100,EOS учитывается. Сохранение настоящего safetensors и
training-manifest/global_step/metrics; при отсутствии данных никакого адаптера.
На нынешнем архиве команда закономерно заблокирована.

training.evaluate готовит100offline contract-сценариев без платных запросов;
--directory указывает локальную библиотеку разработчика, --report — новый файл.
Локальная базовая/обученная модель не выдаются за измеренные,если их нет.
training.export_model требует реальный несмоковый training manifest, совпадающий
SHA адаптера, отсутствие critical regression и владельческое holdout approval.
Это экспорт deployment manifest,не утверждение о проведённой оценке.

training.serve — один выбранный путь: localhost Ollama-compatible /api/chat
поверх локального base+PEFT,без merge/GGUF и публичного доступа. Никакого
предположения,что Ollama умеет читать произвольный LoRA напрямую. Этот сервер
запускается владельцем только при наличии настоящего адаптера/оборудования.
Игра читает trained-narrator.json вне UI,сверяет hash/evaluation/localhost;
неуспех возвращает к RouterAI без повторной игровой транзакции.
