# RouterAI: выдержки из документации, присланные пользователем

Источник: пользовательский ответ в чате 19 октября 2026 и ссылка
https://routerai.ru/docs/reference#tag/api-keys/POST/v1/keys.
Ниже выбранные дословные фрагменты; полный присланный текст остаётся в чате.
Это не результат открытия сайта агентом и не ответ настоящего API.

## Chat completions

Запрос к модели в режиме чата. Поддерживает потоковый и непотоковый режимы.

```sh
curl https://routerai.ru/api/v1/chat/completions \
  --request POST \
  --header 'Content-Type: application/json' \
  --header 'Authorization: Bearer YOUR_SECRET_TOKEN' \
  --data '{
  "model": "deepseek/deepseek-chat-v3.1",
  "messages": [
    {
      "role": "user",
      "content": "Привет, как дела?"
    }
  ]
}'
```

Поддерживает @-синтаксис для передачи routing-параметров прямо в строке
(<model>@provider=<идентификатор>&allow_fallbacks=<true|false>), если клиент
не позволяет задать их в теле запроса.

allow_fallbacks (Boolean, default true) — относится к order: если никого из order
нет, при true запрос уйдёт другому допустимому провайдеру, при false — ошибка 404.
На only/ignore не влияет.

401 Unauthorized - Invalid or missing API key

402 Payment Required - Insufficient balance

## Models

Список доступных моделей. Аутентификация не требуется.

Цены в pricing — в рублях, единица каждого ключа указана в pricing_units с теми
же ключами: token (за токен), request (за запрос, в том числе вызов веб-поиска),
image (за изображение), megapixel (за мегапиксель результата), second
(за секунду аудио/видео), search_unit (за поисковую единицу rerank).

```sh
curl https://routerai.ru/api/v1/models
```

Фрагмент JSON-примера документации, **не текущий тариф**:

```json
{
  "id": "deepseek/deepseek-chat-v3.1",
  "pricing": {
    "prompt": 0.00030631848,
    "completion": 0.0015315924
  },
  "pricing_units": {
    "prompt": "token",
    "completion": "token",
    "image_output": "image"
  },
  "supported_parameters": []
}
```

## API Keys

Создает новый API-ключ. Требуется аутентификация через мастер-ключ.

limit — Type:number, Format:float, default:0. Месячный лимит расходов для API ключа.

Присланный список операций содержит `get /v1/key`. В объектах ключа приведены
`usage`, `limit`, `limit_reset`, `limit_remaining`, `usage_monthly`, `disabled`.
Полный отдельный ответ GET /v1/key в присланном тексте не показан.

В описании PATCH есть неоднозначность: `disabled` и «true если ключ активен,
иначе false». Реальное значение поля ещё не проверено. Код допускает генерацию
только при boolean disabled=false, подтверждённых суммах и положительном остатке.
Неизвестный формат останавливает генерацию; ничего не изменяется через API.

## Границы реализации

В игру добавляется только чат, публичное чтение каталога и чтение текущего
ограниченного ключа. Создание/изменение/удаление/поворот ключей и платежи
из приведённых административных примеров не выполняются. Параметры max_tokens
или max_completion_tokens передаются только при объявлении в supported_parameters
полученного каталога: в присланном примере тела чата их нет.
