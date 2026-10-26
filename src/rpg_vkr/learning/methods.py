"""Original project techniques. Topic references are not quotations from raw corpora."""

SOURCE = "PROJECT-METHODS-2"
EXTRA = (
    (
        "opening",
        "narrative",
        "начало место прибытие сцена introduction arrival",
        "Дай конкретный ориентир и занятого своим делом собеседника. "
        "Остановись перед выбором героя.",
    ),
    (
        "partial",
        "adjudication",
        "неудача частичный провал попытка failure partial",
        "Опиши предел достигнутого по квитанции. Не превращай неудачу в бесплатный успех.",
    ),
    (
        "investigation",
        "adjudication",
        "след улика расследование проверить investigate clue",
        "Отделяй увиденную улику от объяснения её причины. Догадка персонажа остаётся догадкой.",
    ),
    (
        "travel",
        "events",
        "дорога путь путешествие перейти переправа travel journey",
        "Используй подтверждённое место и время. Возможность пути не означает совершённый переход.",
    ),
    (
        "rest",
        "adjudication",
        "отдых привал бытовой безопасный простой rest routine",
        "Простое безопасное занятие не требует выдуманного броска. "
        "Восстановление берётся из правил.",
    ),
    (
        "aftermath",
        "consequences",
        "смерть погиб без сознания рана dead injured aftermath",
        "Различай раненого, потерявшего сознание и погибшего по состоянию "
        "движка. Слух не меняет судьбу.",
    ),
    (
        "politics",
        "behavior",
        "фракция переговоры влияние граница политический diplomacy faction",
        "Покажи несовпадающие интересы участников и доступные сведения. "
        "Соглашение требует их действий.",
    ),
    (
        "reputation",
        "behavior",
        "доверие репутация обещание долг отношение reputation trust",
        "Реакция знакомого опирается на пережитое или услышанное с "
        "источником, без всемирного знания.",
    ),
    (
        "voice",
        "behavior",
        "говорить ответить спросить собеседник диалог voice dialogue",
        "Пусть NPC отвечает на вопрос из своего опыта и занятия. Не "
        "сочиняй следующую реплику героя.",
    ),
    (
        "training",
        "crafting",
        "книга навык учиться практика изучить book training",
        "Получение книги, чтение и освоение навыка — разные события. "
        "Используй подтверждённое развитие.",
    ),
    (
        "ownership",
        "entities",
        "чужой владелец взять вещь подобрать сундук ownership item",
        "Различай видимую вещь, её владельца и доступ героя. Карточка "
        "предмета не выдаёт экземпляр.",
    ),
    (
        "encounter",
        "events",
        "находка событие засада опасность предложение encounter event",
        "Покажи доступные признаки происшествия. Оно допускает отказ и разные способы решения.",
    ),
    (
        "production",
        "crafting",
        "материал станция изготовить руда компонент рецепт алхимия recipe forge",
        "Различай сырьё, компонент и изделие. Ресурсы, инструмент и время "
        "подтверждаются до результата.",
    ),
    (
        "ecology",
        "entities",
        "существо растение монстр зверь среда ecology creature",
        "Поведение существа связано со средой и потребностью. Наличие шаблона не создаёт встречу.",
    ),
)
TOPICS = {
    "narrative": "USER-SYN-1000",
    "consequences": "USER-SYN-DEATH-1000",
    "events": "USER-SYN-EVENTS-1000",
    "behavior": "USER-SYN-BEHAVIOR-5000",
    "entities": "USER-SYN-ENTITIES-5000",
    "adjudication": "USER-SYN-EVERYDAY-1000",
    "crafting": "USER-SYN-CRAFT-5000",
}


def cards():
    from rpg_vkr.learning.rag import CARDS

    spaces = {
        "craft": "crafting",
        "magic": "crafting",
        "knowledge": "behavior",
        "continuity": "behavior",
        "world": "events",
        "stakes": "events",
    }
    values = [(key, spaces.get(key, "narrative"), tags, text) for key, tags, text in CARDS]
    values.extend(EXTRA)
    return {
        "project:" + key: {
            "id": "project:" + key,
            "namespace": namespace,
            "tags": namespace + " " + tags,
            "text": text,
            "source": SOURCE,
            "reference_topic": TOPICS[namespace],
            "quality": "project_authored",
        }
        for key, namespace, tags, text in values
    }
