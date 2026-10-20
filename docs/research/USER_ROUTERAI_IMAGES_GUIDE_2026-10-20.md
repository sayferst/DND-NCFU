# Генерация изображений

> Генерируйте изображения с помощью AI-моделей через RouterAI API.

RouterAI предоставляет выделенный эндпоинт `POST /api/v1/images` для синхронной генерации изображений. Запрос принимает текстовый промпт и сразу возвращает готовые изображения в формате base64. Эндпоинт поддерживают модели, у которых есть `"image"` в списке `output_modalities` (например, `openai/gpt-image-1`, `black-forest-labs/flux.2-pro`, `bytedance-seed/seedream-4.5`).

Диалоговые модели, которые умеют возвращать картинки прямо в переписке (например, `google/gemini-2.5-flash-image`), работают через `/api/v1/chat/completions` — см. раздел «Диалоговые модели генерации изображений» ниже.

## Поиск моделей

### На странице моделей

Откройте [страницу моделей](/models) и отфильтруйте по выходным модальностям — ищите модели с `"image"` в исходящих данных. На странице каждой модели в блоке **Эндпоинт** указано, какой именно эндпоинт она использует, а в блоке **Параметры** — поддерживаемые параметры.

### Через каталог API

Получить список моделей программно можно запросом к `GET /api/v1/models`. Модели генерации изображений содержат `"image"` в `architecture.output_modalities`.

### В чате

В [чате](/chat) выберите модель генерации изображений — появится панель «Генерация изображений» с настройками (соотношение сторон, размер, качество и т.д.).

## Использование API

### Базовая генерация

Отправьте `POST /api/v1/images` с обязательными полями `model` и `prompt`:

```bash
curl https://routerai.ru/api/v1/images \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ROUTERAI_API_KEY" \
  -d '{
    "model": "openai/gpt-image-1",
    "prompt": "Рыжий кот в скафандре на фоне Земли, цифровая иллюстрация",
    "n": 1
  }'
```

Пример на Python:

```python
import requests
import base64

response = requests.post(
    "https://routerai.ru/api/v1/images",
    headers={
        "Authorization": "Bearer $ROUTERAI_API_KEY",
        "Content-Type": "application/json",
    },
    json={
        "model": "openai/gpt-image-1",
        "prompt": "Рыжий кот в скафандре на фоне Земли, цифровая иллюстрация",
        "n": 1,
    },
)

result = response.json()
for i, image in enumerate(result.get("data", [])):
    with open(f"image_{i}.png", "wb") as f:
        f.write(base64.b64decode(image["b64_json"]))
    print(f"Сохранено: image_{i}.png")

print("Стоимость (₽):", result.get("usage", {}).get("cost"))
```

### Параметры запроса

| Параметр | Тип | Описание |
| --- | --- | --- |
| `model` | string | **Обязательно.** Идентификатор модели (например, `openai/gpt-image-1`). |
| `prompt` | string | **Обязательно** для генерации с нуля. Текстовое описание желаемого изображения. Можно опустить при наличии `input_references` (правка/вариации). |
| `n` | integer | Количество изображений за запрос. Максимум зависит от модели. |
| `aspect_ratio` | string | Соотношение сторон (например, `1:1`, `16:9`, `9:16`). |
| `resolution` | string | Тир разрешения: `512`, `1K`, `2K`, `4K`. |
| `size` | string | Точный размер в пикселях (например, `1024x1024`). |
| `quality` | string | Качество: `auto`, `low`, `medium`, `high`; у `openai/gpt-image-2.5-*` также `xhigh` и `max`. |
| `background` | string | Фон: `auto`, `transparent`, `opaque`. |
| `output_format` | string | Формат вывода: `png`, `jpeg`, `webp`. |
| `output_compression` | integer | Степень сжатия `0–100` для `jpeg`/`webp`. |
| `seed` | integer | Сид для воспроизводимости результата. |
| `input_references` | array | Исходные изображения для image-to-image (правка/вариации). |
| `mask` | string \| object | Маска области правки (inpaint) — только модели `openai/gpt-image-*`. PNG с альфа-каналом: прозрачные пиксели — что перерисовать. URL-строка либо объект `{ "image_url": { "url": "..." } }`. Работает только вместе с `input_references`. |
| `input_fidelity` | string | Только `openai/gpt-image-1` и `gpt-image-1-mini`: `high` — сильнее сохранять детали исходника при правке (`gpt-image-2` параметр не принимает). |
| `stream` | boolean | Потоковая отдача превью через SSE. |

> Набор поддерживаемых параметров зависит от модели. Неподдерживаемые значения модель игнорирует или нормализует. Точный список см. в блоке **Параметры** на странице модели.

### Конфигурация изображения

Скомбинируйте параметры под нужный результат:

```bash
curl https://routerai.ru/api/v1/images \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ROUTERAI_API_KEY" \
  -d '{
    "model": "bytedance-seed/seedream-4.5",
    "prompt": "Минималистичный логотип кофейни, плоский дизайн",
    "aspect_ratio": "1:1",
    "resolution": "2K",
    "quality": "high",
    "output_format": "png",
    "background": "transparent"
  }'
```

**Соотношение сторон (`aspect_ratio`).** Распространённые значения — `1:1`, `4:3`, `3:4`, `16:9`, `9:16`, `21:9`. Допустимый набор зависит от модели и указан в таблице параметров на её странице. У `google/gemini-3.1-flash-image`, `google/gemini-3.1-flash-image-preview` и `google/gemini-3.1-flash-lite-image` дополнительно доступны вытянутые форматы `1:4`, `1:8`, `4:1`, `8:1` (баннеры, ленты). Если модель Gemini не поддерживает запрошенное соотношение, оно приводится к ближайшему из её списка.

У моделей `openai/gpt-image-*` соотношение переводится в размер `size`:
- `openai/gpt-image-2.5-*` — точный размер, который зависит ещё и от `resolution` (по умолчанию `1K`):

  | `aspect_ratio` | `1K` | `2K` | `4K` |
  | --- | --- | --- | --- |
  | `1:1` | 1024×1024 | 2048×2048 | 2880×2880 |
  | `3:2` / `2:3` | 1536×1024 | 3072×2048 | 3504×2336 |
  | `4:3` / `3:4` | 1536×1152 | 3072×2304 | 3264×2448 |
  | `16:9` / `9:16` | 1536×864 | 3072×1728 | 3840×2160 |
  | `21:9` | 1568×672 | 3136×1344 | 3808×1632 |

  Для вертикальных форматов стороны меняются местами. `4K` упирается в предел модели: сторона не больше 3840 и не больше 8,3 Мп, поэтому квадрат — 2880×2880. Нужен другой размер — передайте `size` в формате `ШИРИНАxВЫСОТА`: стороны кратны 16, соотношение от 1:3 до 3:1, сторона не больше 3840.
- `openai/gpt-image-1`, `gpt-image-1-mini`, `gpt-image-2` — только `1:1` (1024×1024), `3:2` (1536×1024) и `2:3` (1024×1536).

**Разрешение (`resolution`).** Тиры качества: `512`, `1K`, `2K`, `4K`. Набор зависит от модели: тир `512` есть у `google/gemini-3.1-flash-image` и `-preview`, `google/gemini-3.1-flash-lite-image` работает только в `1K`. У `openai/gpt-image-2.5-*` тиры `1K`, `2K` и `4K` задают размер картинки (таблица выше); `2K` примерно вдвое дороже `1K`, `4K` — в 2,5–3,4 раза в зависимости от формата. Тир, которого у модели Gemini нет, приводится к ближайшему доступному.

**Качество (`quality`).** `auto` (по умолчанию у большинства), `low`, `medium`, `high`. У `openai/gpt-image-2.5-*` есть ещё два уровня выше `high`: `xhigh` и `max`. Качество влияет на цену, но не на размер картинки: у этих моделей счёт идёт за токены изображения, и картинка `1:1` в `1K` в качестве `high` стоит около 1 800 токенов, в `xhigh` — около 3 100, в `max` — около 7 000. Размер задают `aspect_ratio` и `resolution`. Для `quality: auto` уровень выбирает сама модель, поэтому цена заранее не известна.

**Формат и сжатие.** `output_format` — `png` (по умолчанию), `jpeg`, `webp`. Для `jpeg`/`webp` можно задать `output_compression` (0–100).

**Фон (`background`).** `transparent` даёт прозрачный фон (для форматов с альфа-каналом, например `png`/`webp`).

### Редактирование и вариации (image-to-image)

Передайте исходные картинки в `input_references` — модель доработает их по промпту. Каждый элемент — объект `{ "type": "image_url", "image_url": { "url": "..." } }`, где `url` — публичный URL или data URI в base64. Картинку, загруженную через [Files API](/docs/guides/overview/multimodal/files), можно указать по идентификатору: `{ "type": "file", "file": { "file_id": "rai_file_…" } }`.

```bash
curl https://routerai.ru/api/v1/images \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ROUTERAI_API_KEY" \
  -d '{
    "model": "openai/gpt-image-1",
    "prompt": "Сделай фон закатным и добавь тёплое освещение",
    "input_references": [
      {
        "type": "image_url",
        "image_url": { "url": "https://example.com/photo.png" }
      }
    ]
  }'
```

Чтобы передать локальный файл, закодируйте его в base64 и используйте data URI:

```bash
IMAGE_BASE64=$(base64 -w 0 photo.png)

curl https://routerai.ru/api/v1/images \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ROUTERAI_API_KEY" \
  -d "{
    \"model\": \"openai/gpt-image-1\",
    \"prompt\": \"Сделай фон закатным\",
    \"input_references\": [
      {
        \"type\": \"image_url\",
        \"image_url\": { \"url\": \"data:image/png;base64,$IMAGE_BASE64\" }
      }
    ]
  }"
```

### Правка области по маске (inpaint)

Модели `openai/gpt-image-1`, `openai/gpt-image-1-mini` и `openai/gpt-image-2` принимают маску: исходник — в `input_references`, маска — в поле `mask`, изменения описывает `prompt`. Маска — PNG того же размера, что исходник, с альфа-каналом: **прозрачные области** (альфа = 0) отмечают, что перерисовать.

```bash
IMAGE_BASE64=$(base64 -w 0 photo.png)
MASK_BASE64=$(base64 -w 0 mask.png)

curl https://routerai.ru/api/v1/images \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ROUTERAI_API_KEY" \
  -d "{
    \"model\": \"openai/gpt-image-1\",
    \"prompt\": \"Замени объект в выделенной области на вазу с цветами\",
    \"input_fidelity\": \"high\",
    \"input_references\": [
      { \"type\": \"image_url\", \"image_url\": { \"url\": \"data:image/png;base64,$IMAGE_BASE64\" } }
    ],
    \"mask\": { \"image_url\": { \"url\": \"data:image/png;base64,$MASK_BASE64\" } }
  }"
```

Особенности:

- `mask` работает только вместе с `input_references`; без исходника поле игнорируется.
- Точность соблюдения маски зависит от модели. `openai/gpt-image-2` выполняет классический inpaint: изменения строго в области маски, остальной кадр сохраняется. `gpt-image-1` и `gpt-image-1-mini` трактуют маску как мягкое указание — модель генеративно пересоздаёт кадр целиком, и области вне маски могут заметно измениться; для них передавайте `"input_fidelity": "high"` (а для точечной правки часто достаточно `input_references` + подробного промпта вовсе без маски).
- `input_fidelity` принимают только `gpt-image-1`/`gpt-image-1-mini`; `gpt-image-2` на него отвечает ошибкой `invalid_input_fidelity_model`.
- Остальные модели генерации изображений маску не принимают — для них доступна правка всего кадра по промпту через `input_references`.

### Потоковая генерация

С `"stream": true` ответ приходит как поток Server-Sent Events: события `image_generation.partial_image` (превью по мере готовности) и финальное `image_generation.completed` (полный результат с `usage`), затем `[DONE]`.

```bash
curl https://routerai.ru/api/v1/images \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ROUTERAI_API_KEY" \
  -d '{
    "model": "openai/gpt-image-1",
    "prompt": "Футуристический город на закате",
    "stream": true
  }'
```

## Формат ответа

Ответ содержит метку времени `created`, массив `data` с изображениями в base64 (`b64_json`) и `usage` со стоимостью запроса в рублях:

```json
{
  "created": 1735689600,
  "data": [
    {
      "b64_json": "iVBORw0KGgoAAAANSUhEUgAA..."
    }
  ],
  "usage": {
    "cost": 3.4
  }
}
```

### Сохранение изображения

Извлеките base64 из ответа и декодируйте в файл:

```bash
# Ответ сохранён в response.json
cat response.json | jq -r '.data[0].b64_json' | base64 -d > image.png
```

## Диалоговые модели генерации изображений

Некоторые модели генерируют картинки прямо в диалоге и работают через `/api/v1/chat/completions` с параметром `modalities`, включающим `"image"` и `"text"`. Изображения возвращаются в поле `images` сообщения ассистента. Это, в частности, модели Gemini (`google/gemini-2.5-flash-image` и др.), которые помнят контекст переписки.

```bash
curl https://routerai.ru/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $ROUTERAI_API_KEY" \
  -d '{
    "model": "google/gemini-2.5-flash-image",
    "messages": [
      { "role": "user", "content": "Создай красивый закат над горами" }
    ],
    "modalities": ["image", "text"],
    "image_config": {
      "aspect_ratio": "16:9",
      "image_size": "4K"
    }
  }'
```

Модели Gemini поддерживают дополнительную настройку через `image_config` (`aspect_ratio`, `image_size`: `1K`/`2K`/`4K`). Изображения приходят как base64 data URL в `choices[0].message.images[]`:

```json
{
  "choices": [
    {
      "message": {
        "role": "assistant",
        "content": "Готово!",
        "images": [
          {
            "type": "image_url",
            "image_url": { "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..." }
          }
        ]
      }
    }
  ]
}
```

#### Параметры `image_config` (Gemini)

- **`aspect_ratio`** — соотношение сторон → итоговое разрешение (на тире `1K`): `1:1` → 1024×1024 (по умолчанию), `2:3` → 832×1248, `3:2` → 1248×832, `3:4` → 864×1184, `4:3` → 1184×864, `4:5` → 896×1152, `5:4` → 1152×896, `9:16` → 768×1344, `16:9` → 1344×768, `21:9` → 1536×672. У `gemini-3.1-flash-image*` и `gemini-3.1-flash-lite-image` дополнительно: `1:4` → 512×2064, `1:8` → 352×2928, `4:1` → 2064×512, `8:1` → 2928×352.
- **`image_size`** — масштаб разрешения: `1K` (по умолчанию), `2K`, `4K`. Поддерживается только моделями Gemini.

Какой эндпоинт использует конкретная модель, указано в блоке **Эндпоинт** на её странице.

## Лучшие практики

- **Подробные промпты.** Чем точнее описание (стиль, композиция, освещение), тем лучше результат.
- **Параметры под задачу.** Прозрачный фон — `background: "transparent"` + `output_format: "png"`; меньший вес файла — `jpeg`/`webp` с `output_compression`.
- **Итеративная доработка.** Чтобы изменить уже сгенерированную картинку, передайте её в `input_references` следующего запроса (image-to-image).
- **Хранение.** Изображения приходят в base64 — продумайте декодирование и хранение.

## Устранение неполадок

**Ошибка «model not served» или 503?**

- Убедитесь, что у модели есть `"image"` в `output_modalities` (см. [страницу моделей](/models)).

**Пустой `data` в ответе?**

- Проверьте, что промпт описывает желаемое изображение, а параметры (`size`, `aspect_ratio`, `quality`) поддерживаются моделью.

**Нужна правка изображения, а не генерация с нуля?**

- Передайте исходник в `input_references`. Для правки `prompt` описывает требуемые изменения.
