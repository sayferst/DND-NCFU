# Приёмка единого потока DND-NCFU — 26–27.10.2026

## 1. Исходное состояние и изменённый интерфейс

Изучен чистый setup/development-environment@468f7744ec1c. Исходное состояние
зафиксировано до реализации в architecture_before.md/change_map.md,
validation/baseline-01.txt:1851passed. Работа:feature/unified-rpg-automatic-gm.
Точное объединённое ТЗ сохранено как source-spec.md,369строк,
SHA2569568f5b92075fcfd4912077150c176db2db80b859408eb99232ef603486f33b6.
Прежние отдельные задания/исторические статусы больше не определяют UX новой игры.

Из конструктора удалены use_d20_skills/use_gameplay/generate_world,
вид/возраст/происхождение отдельными полями,второй профиль,ранги/13очков.
Из production DeveloperConsole удалена вкладка LearningPanel целиком.
В игровом интерфейсе нет ZIP/review/rebuild/RAG-mode/выбора версии приключения
или миграции29. Старый файл learning_panel.py оставлен только внутренней
совместимости/историческим тестам,production его не создаёт.

## 2. Создание и реальный запуск

Четыре страницы: имя/один класс/автоматический комплект → характеристики/талант
→ два свободных текста → подтверждение. Кнопка создания только на последней.
База8,ровно24повышения,каждая характеристика8–16,один талант; рекомендации
применяются явной кнопкой,есть модификаторы/tooltip/ресурсы. Тексты6000/3000
символов сохраняются без переписывания. Ошибка не уничтожает диалог/нового героя.

После подтверждения начинается настоящая генерация мира существующим
RouterAI pipeline,без второго выбора режима и молчаливого tutorial fallback.
При ненастроенном подключении показана ошибка/повтор,не выдуманный готовый мир.
В account release провайдером по-прежнему управляет владелец,не игрок.
В developer release существующая админ-настройка RouterAI сохранена.

## 3. Классы,предметы,бой,ремесло

| Класс | Фактический комплект |
| --- | --- |
| Воин | Меч,щит,кожаный доспех,2бинта |
| Лучник | Лук,кинжал,12стрел,бинт |
| Плут | Кинжал,отмычки,кожаный доспех,бинт |
| Маг | Посох,свиток света,свиток лечения,2зелья маны |
| Жрец | Кинжал,символ веры,2бинта |
| Ремесленник | Кинжал,инструменты,ткань,2железа,древесина |

Везде200медных/один кошелёк. Предметы с ID,ownership,износом. Экипировка,
стрелы,свитки/лекарства,MP/ST,материалы меняются только после валидированной
операции. Свиток одноразовый,мана+до6MP; при отказе возвращаются и состояние,
иRNG. Купленная единица отделяется от реальной стопки; проданный/использованный
source перестаёт принадлежать герою во всех проекциях. Buy-sell-rebuy и
повторная продажа/расход проверены реальной Session и replay.

Общая очередь до8участников,настоящие атаки героя/согласившихся союзников/NPC,
магия/расходники занимают ход; попадание/крит/броня/HP рассчитываются кодом.
Подготовка класса автоматическая,атрибуты/таланты применяются в броске.
Панель «Герой и действия» вызывает эти операции,не демонстрационную математику.

Минимальный каталог новой игры: свет/магический разряд/исцеление;4рецепта
(слиток/меч/мана/бинт),ремонт,конечная добыча. Время/потребности/производство/
зарплаты/фракционные сообщения используют существующий конечный sandbox,
без LLM на каждогоNPC. Это не полный SRD,не26старых заклинаний и не5000
исполняемых рецептов. Темп/баланс всей20уровневой кампании не измерены.

## 4. Единственные новые правила и старые сохранения

АктивныйID новых игр:dnd-ncfu-unified-d20-v1,schema30,UnifiedSession.
Формулы/каталог:src/rpg_vkr/domain/unified.py и ruleset.md.
DiceRoller:domain/dice.py,реальныеD4/D6/D8/D10/D12/D20/D100/seed/checkpoint.
Уровень порогаL:50*(L−1)*L,cap20;подготовка+2…+6;повышения4/8/12/16/20,
таланты1/5/10/15/20. Никакой второй валюты рангов.

Схема30 хранит origin+whitelist операций+снимок; reader повторяет validators
и сверяет всё,включаяRNG. JSON/SQLite сохраняют полную обёртку. Подмена
монет/предметов отклоняется. Старые1–29 читаются прежними reader/handlers,
без автоматической переклассификации scout. Все86защищённых файлов иAGENTS
совпали с468f774:validation/immutable-audit-final.json. Подробности:migration.md.

## 5. Автоматическая база

data/approved_knowledge/index.json:24оригинальных безопасных метода проекта,
SHA/ограничение размера/допуск проверяются при загрузке.0–3коротких подсказки
автоматически добавляются в реальный narration prompt; отсутствие/повреждение
индекса даёт пустой результат и не ломает игру. Механика/факты не берутся из него.

Developer CLI training.build_embedded_knowledge воспроизводит этот артефакт;
дополнительные разрешённые выдержки принимаются только из reviewed train,
с явным публичным допуском. Raw/частные сюжеты не копируются в installer.
PyInstaller явно включает index,но допускает его отсутствие. Игрок не импортирует
архив и не выбирает библиотеку/версию/модель ради базы.

## 6. Что реально находится в архиве

Проверен DND_Training_Package_CODEX_READY (1).zip:
SHAf1a7568e3461f7c2edc0e8badf1bc87f3c2eae7df085762b02a6058baa8146fe.
19файлов,8корпусов,19200структурных записей,200aliases,19000canonical.
Это карточки/примеры,не подтверждённые19000сессий. Полных одобренныхSFT-пар
с public_context/реальной engine_receipt/assistant_reply —0;campaigns0.
Raw и производная частнаяSQLite остаются внеGit/клиента/провайдера.

## 7. Обучение: фактически не выполнялось

Основной конкретный блокер:нет одобренного набора реальныхSFT-пар. Preflight
BLOCKED_DATA,training_started=false.0gradient steps,0checkpoints,
нетadapter_model.safetensors и новых весов. СредаLinux3CPU/~9.7GiBRAM,
нетNVIDIA/CUDA; оборудование владельца здесь не проверялось.

Реализованы отдельные безопасныеinspect/redact/validate/dedup/campaignsplit,
privacy gate,QLoRA Trainer/PEFT,smoke2steps,реальныйsave/manifest/hash,
экспорт с holdout gate и localhostserve. КонфигурацияJSON:Qwen/Qwen3-4B,
revision1cfa9a7208912126459214e8b04321603b3df60c,apache-2.0,NF4/BF16,r16,
alpha32,dropout.05,LR1e−4,maxlen2048,batch1,accum16,epoch1,seed37.
Metadata проверены,веса не скачаны. GPU-path/качество фактически не проверены.
Запуск/формат/права:training/README.md и docs/ml/*.md.

## 8. RouterAI,trained narrator и бюджеты

Прежние RouterAItransport/ключи/каталог/квоты не заменены. Новых платных
запросов в этом задании0. Старые72liveответа относятся к прошлому этапу,
не названы новой baselineоценкой. Веса RouterAI не менялись.

Owner-only trained-narrator.json вне репозитория допускает localhostbackend
только при реальном adapterSHA/manifest/holdoutapproval. При отсутствии/ошибке
работает прежний RouterAI. Fallback меняет только рассказ,не исполняет второй
раз Sessionоперацию. Настоящего обученного backendсейчас нет;loopbackfixture
не объявлен trainedinference. Training/Torch/модели исключены из installer.

Длины адаптивны:цена1–3предложения,обычный осмотр60–150слов как ориентир,
важная сцена130–300,вступление250–500с достаточным outputbudget. WorldSeed2
допускает7500символов только новых кампаний;старыйv1/лимит3500не изменён.
Receipt/агентность/тайны остаются валидируемыми,большой бюджет не создаёт факты.

## 9. Фактическая QA

Команды:

```bash
.venv/bin/python scripts/check.py
.venv/bin/python -m pytest tests/test_unified_rules.py -q
.venv/bin/python -m training.inspect_archive --input '...CODEX_READY (1).zip' --report NEW.json
.venv/bin/python -m training.prepare_dataset --input '...CODEX_READY (1).zip' --output data/processed/gm-sft-v1 --dry-run
.venv/bin/python -m training.train_lora --config training/configs/one_qlora_config.json --dry-run
.venv/bin/python -m training.evaluate --directory /tmp/unified-offline-evaluation --report NEW.json
.venv/bin/python -m PyInstaller --noconfirm DND-NCFU.spec
```

Полные результаты и последовательность неуспешных попыток сохранены вvalidation/.
full-check-06:1879passed/314.09с,pip/Ruffcheck/format327файлов успешны.
Последняя торговая регрессияrules-07:16passed/0.77с.
full-check-07: **1880passed/302.93с**,0failed;pipcheck/Ruffcheck/
format327файлов успешны. Затем проверен свободный маршрут AI-проверок:
canonical validator вместо старых ranks/DC5–25,чистая характеристика без
незаслуженной подготовки,правильное Телосложение для нагрузки.
canonical-checks-02:63passed/2.63с,включая настоящую кнопкуUI/Session/replay.
В developer evaluate также уточнена подпись legacy-метрики,повтор CLI/целевых
тестов сохранён отдельно. full-check-08:1882passed/301.50с,затемRuffнашёл
одну длинную строку. Она разделена на соседние литералы без изменения текста
prompt;Ruffcheck/formatпосле исправления успешны. Итоговыйfull-check-09:
**1882passed/288.86с**,0failed,pipcheck/Ruffcheck/format327файлов успешны,
scripts/check.py exit0. Он выполнен на окончательных исходниках;
неуспешный08сохранён без переписывания.
linux-build-03 завершён;linux-self-check-03 и linux-smoke-04:ok=true.
Проверены настоящий bundledконструктор/автомир/JSON/SQLite/RNG и fallbackfixture,
external_model_requests=0. packaging-audit-02:24-методныйindex включён,
training/Torch/raw/weights не включены. Это Linuxbundle,не выпущенный WindowsSetup.

100offlineсценариев×4условия проверяют validators/context,не качество модели:
0validator mismatches/unsafe accepts,Session/RNG неизменны. Автоматический
встроенныйindex уже есть во всех условиях;это не изолированное A/B его эффекта.
Base local/trained/livehybrid:NOT_DEPLOYED/NOT_TRAINED/NOT_MEASURED.
Часть20критериев проверена общими инвариантами прежнего движка,не отдельным
новым одноимённым файлом:

| Критерии ТЗ | Реальные тесты/граница |
| --- | --- |
|1/2/5/20:creator/валидация/UX|test_unified_creation,creation_and_roles,world_creation_screen,launch;offscreen и скриншоты,Windows/DPIне проверены|
|3/4/6/7:классы/расход/развитие|test_unified_rules,unified_creation;6классов,пороговые уровни,подготовка,реальныеinventory/MP/scroll|
|8/9:dice/бой|test_polyhedral_dice,test_dice,unified_rules;общийRNG,настоящие teamattack/bolt/NPC/receipt|
|10/12:агентность/тайны/частичный исход|существующие test_chat_intents,test_master_campaign,test_story_conversation_quality,test_world_memory,квитанции/планировщик;новыйrulesetне отдаёт прозе права записи|
|11:длина/цена/осмотр|test_scene_length_and_receipts,master/storycontracts;литературныйliveэффектне измерен|
|13/14:RouterAI/автобаза|test_routerai_narrator_fallback,embedded_knowledge,world_creation_screen;provider/budgetregressionsвполномнаборе|
|15/16/17:данные/adapter|test_training_pipeline,tests/learning;privacy/rights/groupedsplit,unapprovedrejected;реальногообучениянет|
|18:таймаут/двойная награда|unified_rules requestid/RNG/replay,routerai_narrator_fallback;проза неисполняетход|
|19:сохранения|историческиеfixture/replaytests,unified_rules JSON/SQLite/tamper,longWorldSeed2;86protectedSHAнеизменны|

Непроверено:WindowsGUI/DPI/DPAPI/Setup,чистаяWindowsбезPython,фактическийGPU
train/serve/holdout,liveхудожественноеA/B/VRAM/стоимость,20уровневыйбаланс.

## 10. Изменённые файлы,скриншоты,порядок включения

Основные новые модули:domain/unified.py,unified_session.py,ui/unified_panel.py,
learning/embedded.py,narrative/trained_backend.py. Переработаны
ui/creation_dialog.py и точкиSession/сохранений/контекста/receipt/UI.
Отдельныеtraining/,docs/ml/,data/approved_knowledge/,тесты иDND-NCFU.spec.
Полная карта:change_map.md;историческиеhandlers/fixtures не менялись.

Скриншоты настоящихQtwidgets: [Герой](screenshots/hero.png),
[Характеристики](screenshots/attributes.png),[История](screenshots/story.png),
[Подтверждение](screenshots/confirmation.png),
[Консоль без библиотеки](screenshots/developer-console.png).

Новая механика и база работают автоматически после обновления и создания
нового героя;старый save продолжает прежние правила. Никаких ZIP/ML-флагов
для игрока. ЗапускPowerShell:

```powershell
Set-Location D:\Projects\DND-NCFU
git fetch origin
git switch feature/unified-rpg-automatic-gm
git pull --ff-only
.\.venv\Scripts\python.exe scripts\check.py
.\.venv\Scripts\python.exe scripts\run_game.py
```

Игровые зависимости не добавлены. Существующие несохранённые локальные файлы
не стирать;gitstatus перед переключением. Ownertraining — отдельный процесс,
не настройка игрока;до появления реальных данных обучение не запускается.
