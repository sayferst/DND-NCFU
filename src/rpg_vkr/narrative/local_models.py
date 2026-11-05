"""Local provider identity; no training dependencies in the packaged game."""

import re

FAUN_MODEL = "hf.co/limloop/MN-12B-Faun-RP-RU-GGUF:Q4_K_M"
FAUN_LABEL = "MN-12B-Faun-RP-RU — локальная модель"


def local_models(data):
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("Invalid model list")
    result = []
    for item in data["models"]:
        if not isinstance(item, dict):
            raise ValueError("Invalid model entry")
        name = item.get("name", "")
        if (
            isinstance(name, str)
            and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", name)
            and "cloud" not in name.casefold()
            and not item.get("remote_host")
            and not item.get("remote_model")
            and type(item.get("size")) is int
            and item["size"] > 0
        ):
            result.append(name)
    return tuple(dict.fromkeys(result))
