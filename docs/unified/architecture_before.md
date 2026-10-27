# Исходное состояние перед единым потоком

Исследован468f774, чистый checkout setup/development-environment.
Рабочая ветка feature/unified-rpg-automatic-gm. SHA нового ТЗ и оборудование:
validation/environment-01.json. Baseline: validation/baseline-01.txt.

| Объект/ветвь | Хранение и зависимости | Решение |
| --- | --- | --- |
| CreationDialog.use_d20_skills/use_gameplay/generate_world | Session.enable_d20_progress/enable_gameplay; схемы23–28 | Удалить из нового конструктора |
| class_choice + profile_choice + species_choice/age/background/appearance | HeroProgress + gameplay.identity | Один новый класс, описание свободным текстом |
| initial_skills,13очков, skill_panel | D20Progress, campaign_progress | Не создавать для новых героев; оставить reader старых сохранений |
| пять вкладок CreationDialog + общий Create | main_window.new_character; world_creation_screen | Четыре шага, одно подтверждение, автозапуск генерации |
| campaign_v5_panel RAG off/shadow/hints/копия | learning.json, миграция29 | Удалить ручной RAG из нового потока |
| DeveloperConsole.learning | LearningPanel/QThreadPool/localSQLite | Удалить вкладку целиком; оставить CLI |
| Session -> gameplay_session -> gameplay_rules | версии24–28, атомарный RNG, typed receipts | Старые обработчики не менять; новый канонический обработчик |
| migration29 | source + operations + snapshot, replay | Сохранить совместимость; новая схема отдельно проверяется повтором операций |
| RouterAI | cloud.py transport, routerai.py каталог/квота, OllamaClient async stages | Сохранить ключи/бюджеты/планировщик; заменить контекст новых правил |
| память | CampaignRepository/SaveSlots, knowledge, learning.memory | Один канон Session, выборка по world/hero/NPC |
| архив | 19000raw локальнаяSQLite,0human approved;24оригинальных метода | Автоматически упаковать безопасные оригинальные методы, не raw |

Фактические кубики DiceRoller уже поддерживают NdM±K/D4–D100 и checkpoint.
Разные старые формулы нельзя перебалансировать при replay. Новый ruleset
использует шесть характеристик8–16/бюджет24, подготовку класса вместо рангов.
HP/ST/MP опираются на формулы hero_resources, с отдельной фиксированной версией.
Игровой маршрут: ввод -> план RouterAI -> Session/валидатор -> receipt -> prose.
Проза не является операцией. Старые JSON/SQLite остаются доступными без конверсии.

В этой среде Linux,3CPU,около9.7GiB RAM,нет NVIDIA устройств/nvidia-smi/PyTorch.
Есть исходный CODEX_READY вне Git; человечески одобренных SFT-пар0.
Наличие19000карточек не доказывает пригодность их для обучения весов.
