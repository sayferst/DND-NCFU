# Перенос Faun QLoRA на внешний GPU

Актуальный готовый пакет и сравнение цен: [TRAINING_TRANSFER.md](TRAINING_TRANSFER.md).

Состояние: подготовлены инструменты, **обучение не выполнялось:0 шагов,0 адаптеров**.
На Acer с Iris Xe выбранный NVIDIA CUDA/BF16-профиль блокируется по оборудованию.
Характеристики компьютера друга неизвестны. Аренда и платные сервисы не запускаются.
Совместимость стека с12B подтверждается только настоящим smoke-test на выбранном GPU.

Из проекта можно собрать небольшой ZIP только с инструментами:

```powershell
.\.venv\Scripts\python.exe -m training.setup_faun_gpu --bundle ..\DND-NCFU-data\faun-training-tools.zip
```

Требуется новое имя файла. Белый список содержит код подготовки/проверки данных,
обучения, локальной оценки и экспорта, профиль модели, Linux-lock и чистые
зависимости исходного кода. Manifest содержит SHA каждого файла. В архив не входят
сейвы, ключи, датасеты, приватные кампании, веса или результаты оптимизации.
Проверен запуск train dry-run из распакованного архива без полного приложения.

Дальнейшие команды выполняет владелец разрешённого компьютера **из распакованного
корня под Linux/WSL2, Python3.12**. Драйвер NVIDIA должен уже поддерживать CUDA;
скрипт не устанавливает драйверы и не меняет Windows/WSL.16ГиБ VRAM — нижний
предварительный порог, не обещание вместимости; предпочтительно24ГиБ и больше.
Для исходных весов/кэша требуется60ГиБ свободного диска; merge требует ещё больше.
При нескольких GPU выберите совместимую карту через CUDA_VISIBLE_DEVICES перед
запуском: обучение использует устройство0 внутри процесса. Наличие другой
подходящей карты в общем списке nvidia-smi не доказывает пригодность выбранной.

```bash
python3.12 -m training.hardware_preflight --scope friend_gpu --output hardware-friend-001.json
python3.12 -m training.setup_faun_gpu --install-stack
python3.12 -m training.setup_faun_gpu --download-base
```

Первая команда только читает оборудование. Вторая после отдельного подтверждения
создаёт `.venv-faun`, устанавливает зависимости из `requirements-faun-linux.lock`
с `--require-hashes` и сохраняет фактический pip freeze. Lock разрешён для Linux
x86_64/Python3.12; чужие платформы не считаются проверенными. Это отдельный candidate
стек, не обновление игры или рабочей Qwen-конфигурации.

Третья команда отдельно спрашивает о загрузке примерно24ГБ исходных Safetensors.
Используется `limloop/MN-12B-Faun-RP-RU`, revision
`bdfc761b14feb9dd03ef158a4d337fc1cf5fd183`. GGUF для обучения не подходит.
Проверяются CUDA/BF16, архитектура, hash шаблона чата и индекс Safetensors.
После загрузки записываются SHA реальных шардов; повторный запуск сверяет их и
не запускает snapshot_download для уже подтверждённой копии. Никакой remote code
не выполняется. Большие зависимости и веса в этой Codex-сессии не скачивались.

## Данные и запуск

Передавать на чужой компьютер можно только отдельно одобренные обезличенные
данные с подтверждёнными правами. Текущий допущенный SFT-корпус пуст.
Автоматическое копирование частных кампаний в инструментах отсутствует.

```bash
.venv-faun/bin/python -m training.prepare_dataset --input reviewed.jsonl --output data/processed/gm-sft-v1 --confirm-privacy-review
```

Эта команда допустима только **после** реальной проверки владельцем и участниками;
флаг не заменяет согласие. Каждая запись должна соответствовать gm-sft-v1,
иметь approved/permitted, реальную квитанцию и не быть synthetic fixture.
Подготовщик проверяет схему, права, приватность и группировку кампаний/дублей.
Запишите SHA из manifest в **копию** faun_qlora_v1.json, выберите новую output-папку.
Не изменяйте Qwen-профиль. Для smoke и полного запуска используйте разные output.

```bash
.venv-faun/bin/python -m training.train_lora --config faun-smoke.json --dry-run
.venv-faun/bin/python -m training.train_lora --config faun-smoke.json --smoke-test
.venv-faun/bin/python -m training.train_lora --config faun-run.json
```

Dry-run обязан вернуть READY до запуска. Smoke выполняет2 настоящих шага
оптимизации, не симуляцию. Реальное обучение маскирует prompt в loss, проверяет
Faun ChatML, фиксирует seed, сохраняет Trainer checkpoints каждые100 шагов,
адаптер и manifest с фактическими шагами/metrics/GPU/SHA; адаптер повторно загружается.
При меньшем числе шагов manifest и финальный адаптер есть, промежуточного
checkpoint-100 может ещё не быть. Ошибки/OOM нельзя выдавать за обучение.

Для прерванного полного запуска с реально существующим checkpoint:

```bash
.venv-faun/bin/python -m training.train_lora --config faun-run.json --resume-from-checkpoint artifacts/faun-run/checkpoint-100
```

Output должен совпадать с конфигурацией; сверяется hash конфигурации в
run-provenance и ненулевой global_step в Trainer state. Checkpoint из другой
папки либо изменённая конфигурация отклоняются. Без явного resume существующая
output-папка не перезаписывается. run-provenance сам по себе не доказывает
выполненную оптимизацию: для результата нужны настоящий manifest и веса.

## Независимая оценка и экспорт

`training.evaluate_faun` проверяет SHA всех split, права, review и отсутствие
пересечения ID/кампаний, затем использует **только test**. Без --run-local
инференс не запускается. Примеры и near-дубли должны разделяться ещё на этапе
подготовки; механическая проверка ID не доказывает семантическую независимость.
Оценка не использует эталонный ответ в промпте и не назначает человеческую оценку.

Если базовая Faun уже разрешена и установлена в локальной Ollama:

```bash
.venv-faun/bin/python -m training.evaluate_faun --directory data/processed/gm-sft-v1 --run-local --limit 20 --output faun-base-holdout-001.json
```

Для настоящего несмокового адаптера в отдельном терминале:

```bash
.venv-faun/bin/python -m training.serve --config faun-run.json --adapter artifacts/faun-run --port 11435
.venv-faun/bin/python -m training.evaluate_faun --directory data/processed/gm-sft-v1 --run-local --port 11435 --model dnd-trained-narrator --limit 20 --output faun-adapter-holdout-001.json
```

Сервер слушает127.0.0.1; оценщик не принимает HTTP-redirect и не использует proxy.
Выход содержит реальные тексты/латентность/digest и ограниченный rule critic;
отсутствие его замечаний **не означает** полную проверку фактов или литературного
качества. Нужен независимый ручной holdout-review. Базовую и обученную Faun
сравнивают на тех же ID, prompts, лимитах и железе. Сравнение с DeepSeek требует
отдельного разрешения на соответствующий API; здесь оно NOT_RUN.

После реальной оценки `training.export_model` требует несмоковый manifest,
SHA адаптера и отдельное владельческое одобрение holdout без критической регрессии.
Только затем `training.merge_gguf` может объединить локальный base+PEFT и
конвертировать через уже установленный llama.cpp в Q4_K_M. По умолчанию у merge
только preflight; `--execute` — отдельное явное действие. Нужны сам llama.cpp,
достаточно RAM/диска и актуальная проверка лицензий. Автовключения адаптера в игру нет.

Код процесса и metadata-lock готовы к проверке; настоящий GPU batch, совместимость
библиотек, обучение, reload, независимая оценка и GGUF-экспорт ещё не выполнялись.
