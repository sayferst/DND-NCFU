"""Closed master requests select pinned templates; the engine builds entities."""

import os
import re
import sqlite3
from pathlib import Path

from rpg_vkr.domain.catalog import Registration, register, seed_catalog
from rpg_vkr.domain.interactions import identifier
from rpg_vkr.world_library.bridge import preview
from rpg_vkr.world_library.model import digest
from rpg_vkr.world_library.store import Library

GUIDE = (
    "Для нового экземпляра из world_library верни отдельный план с steps=[], "
    "places=[], check=none, без catalog, gameplay, queries, trade, attempt, reply и memories. "
    "Поле library_requests: "
    '[{"template_id":"ID карточки","instance_id":"новый ID экземпляра",'
    '"revision":1,"digest":"digest карточки","with_inventory":false}]. '
    "Не переписывай характеристики: Python возьмёт их из закреплённого шаблона. "
    "Разрешены до двух заявок из полученных карточек. Они создают объекты в сцене, "
    "а не в инвентаре героя; решение подтверждается перед применением. "
    "Для NPC with_inventory=true создаёт указанное начальное имущество у NPC. "
    "Карточки с mechanics.version=descriptive являются справками, а не экземплярами."
)


def validate_requests(value, context):
    if type(value) is not list or len(value) > 2:
        raise ValueError("Expected up to two template requests")
    if not value:
        return []
    if not context or context.get("status") != "matched":
        raise ValueError("Connect the catalog before requesting templates")
    allowed = {c["id"]: c for c in context.get("cards", [])}
    ids = set()
    for request in value:
        if type(request) is not dict or set(request) != {
            "template_id",
            "instance_id",
            "revision",
            "digest",
            "with_inventory",
        }:
            raise ValueError("Template requests cannot assign arbitrary properties")
        identifier(request["instance_id"])
        if not isinstance(request["template_id"], str):
            raise ValueError("Template ID must be text")
        selected = allowed.get(request["template_id"])
        if not selected or selected["mechanics"]["version"] == "descriptive":
            raise ValueError("Select an executable template from the supplied cards")
        if (
            type(request["revision"]) is not int
            or request["revision"] != selected["revision"]
            or not isinstance(request["digest"], str)
            or not re.fullmatch("[0-9a-f]{64}", request["digest"])
            or request["digest"] != selected["digest"]
            or type(request["with_inventory"]) is not bool
            or request["instance_id"] in ids
        ):
            raise ValueError("Stale or invalid template request")
        ids.add(request["instance_id"])
    return value


def prepare(session, requests, *, path=None, model="world-master"):
    if type(requests) is not list or not 1 <= len(requests) <= 2:
        raise ValueError("Expected one or two template requests")
    required = {"template_id", "instance_id", "revision", "digest", "with_inventory"}
    if any(type(r) is not dict or set(r) != required for r in requests):
        raise ValueError("Invalid template request fields")
    if any(not isinstance(r["template_id"], str) for r in requests):
        raise ValueError("Template ID must be text")
    configured = path or os.environ.get("RPG_VKR_WORLD_LIBRARY")
    if not configured or not Path(configured).is_file():
        raise ValueError("Choose an existing world library")
    connection = sqlite3.connect(Path(configured).resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    library = Library(connection)
    try:
        connection.execute("BEGIN")  # Approval binds one consistent read snapshot.
        definitions, entities = {}, {}
        context = {"status": "matched", "cards": []}
        for request in requests:
            row = library.get(request["template_id"])
            from rpg_vkr.world_library.model import validate_record

            validate_record(row)
            context["cards"].append(
                {
                    "id": row["id"],
                    "revision": library.revision(row["id"]),
                    "digest": digest(row),
                    "mechanics": {
                        "version": "descriptive"
                        if row["profile"] in {"source_reference", "skill", "race"}
                        else "engine-template"
                    },
                }
            )
        validate_requests(requests, context)
        for request in requests:
            record = preview(
                library,
                session,
                request["template_id"],
                request["instance_id"],
                with_inventory=request["with_inventory"],
            )
            for definition in record.definitions:
                if definition.id in definitions and definitions[definition.id] != definition:
                    raise ValueError("Conflicting template dependencies")
                definitions[definition.id] = definition
            for entity in record.entities:
                if entity.id in entities:
                    raise ValueError("Duplicate requested entity")
                entities[entity.id] = entity
        record = Registration(
            tuple(definitions.values()),
            tuple(entities.values()),
            "Создание из библиотеки world-library-request-1",
            model,
            len(session.turns),
            session.interaction_state(),
        )
        register(session.catalog or seed_catalog(), session.interaction_state(), record)
        return record
    except sqlite3.DatabaseError as error:
        raise ValueError("World library could not be read") from error
    finally:
        library.close()
