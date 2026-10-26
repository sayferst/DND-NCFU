# Фактические границы провайдера

| Возможность | Что установлено в этом checkout |
| --- | --- |
| RouterAI inference | narrative/cloud.py: https://routerai.ru/api/v1/chat/completions |
| Model ID | storage/connection.py FLASH_MODEL: ~deepseek/deepseek-v4-flash-latest; пользовательские настройки могут отличаться |
| Системные инструкции | narrative/instructions.py, story_prompt.py; пакетные промпты их не перезаписали |
| Роли/числа | Интерпретатор предлагает действие, Python валидирует/считает, рассказчик описывает квитанцию |
| Повтор/бюджет/отмена | Существующие tests/test_model_metrics.py; синтетические локальные HTTP-серверы |
| Платный живой вызов | Не выполнялся |
| RAG/embeddings по новому пакету | Не подключены; индекс0 |
| Fine-tuning API именно этого hosted-чекпойнта | UNKNOWN, нет проверенного training-контракта в проекте |
| Запуск SFT/LoRA | Не выполнялся; нет одобренных training-примеров и задания провайдеру |

Статус экспорта на обучение: BLOCKED_PROVIDER_TRAINING / BLOCKED_DATA_REVIEW.
Обычный inference не изменяет веса. В этом этапе нет сравнительной человеческой
оценки прозы и нет доказанного прироста качества модели. Состояние API-ключей,
конфигурация хоста, лимиты и DPAPI-хранилища не менялись.
