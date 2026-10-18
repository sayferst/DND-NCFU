"""Validate a model's proposed intent before the rules engine sees it."""

from dataclasses import dataclass

from rpg_vkr.commands import CHAT_TARGETS, allowed_intents


@dataclass(frozen=True)
class Interpretation:
    kind: str
    command: str
    target: str
    question: str


def intent_schema(target=None):
    from rpg_vkr.narrative.speech import command_target

    commands = sorted(
        command
        for command in allowed_intents()
        if not target or (command != "поговорить" and command_target(command) in {None, target})
    )
    return {
        "type": "object",
        "properties": {
            "command": {"type": "string", "enum": commands},
        },
        "required": ["command"],
        "additionalProperties": False,
    }


def parse_interpretation(data):
    import json

    if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
        raise ValueError("Missing intent message")
    message = data["message"]
    if message.get("role") != "assistant":
        raise ValueError("Invalid intent role")
    value = json.loads(message["content"])
    if isinstance(value, dict) and set(value) == {"command"}:
        command = value["command"]
        if not isinstance(command, str) or command not in allowed_intents():
            raise ValueError("Unsupported action")
        if command in CHAT_TARGETS:
            return Interpretation("dialogue", "", CHAT_TARGETS[command], "")
        if command == "уточнить намерение":
            return Interpretation("clarify", "", "", "")
        return Interpretation("action", command, "", "")
    # Accept the previous bounded wire contract too; never infer missing fields or effects.
    if not isinstance(value, dict) or set(value) != {"kind", "command", "target", "question"}:
        raise ValueError("Invalid intent fields")
    if not all(isinstance(v, str) for v in value.values()):
        raise ValueError("Invalid intent types")
    result = Interpretation(**value)
    if result.kind == "action":
        if result.command not in allowed_intents() - set(CHAT_TARGETS) - {"уточнить намерение"}:
            raise ValueError("Unsupported action")
        if result.target or result.question:
            raise ValueError("Mixed action and dialogue")
    elif result.kind == "dialogue":
        if result.target not in CHAT_TARGETS.values() or result.command or result.question:
            raise ValueError("Invalid dialogue target")
    elif result.kind == "clarify":
        if result.command or result.target or not 1 <= len(result.question.strip()) <= 500:
            raise ValueError("Invalid clarification")
        from rpg_vkr.narrative.ollama import validate_prose

        validate_prose(result.question)
    else:
        raise ValueError("Unknown intent kind")
    return result
