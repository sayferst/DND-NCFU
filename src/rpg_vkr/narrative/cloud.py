"""Optional HTTPS chat-completion API; never uses ChatGPT subscriptions or cookies."""

import re
from dataclasses import dataclass, field

ENDPOINTS = {
    "openai": "https://api.openai.com/v1/chat/completions",
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
}


@dataclass(frozen=True)
class CloudProfile:
    provider: str
    model: str
    key: str = field(repr=False)
    free_only: bool = False

    def __post_init__(self):
        if self.provider not in ENDPOINTS:
            raise ValueError("Неизвестный API-провайдер.")
        if not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", self.model):
            raise ValueError("Укажите идентификатор облачной модели.")
        if not self.key or any(c.isspace() for c in self.key):
            raise ValueError("Укажите API-ключ провайдера, не пароль ChatGPT.")
        if type(self.free_only) is not bool:
            raise ValueError("Неверный режим оплаты API.")
        if self.free_only and (
            self.provider != "openrouter"
            or not (self.model == "openrouter/free" or self.model.endswith(":free"))
        ):
            raise ValueError(
                "Для бесплатного режима OpenRouter выберите openrouter/free "
                "или существующую модель с суффиксом :free."
            )

    @property
    def endpoint(self):
        return ENDPOINTS[self.provider]

    def payload(self, local):
        result = {"model": self.model, "messages": local["messages"], "stream": False}
        limit = local.get("options", {}).get("num_predict", 650)
        result["max_completion_tokens" if self.provider == "openai" else "max_tokens"] = limit
        if not self.model.startswith(("gpt-5", "o1", "o3", "o4")):
            result["temperature"] = local.get("options", {}).get("temperature", 0.45)
        if self.free_only:
            result["provider"] = {
                "max_price": {"prompt": 0, "completion": 0, "request": 0},
                "allow_fallbacks": False,
            }
        return result


def normalize_completion(data):
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("choices"), list)
        or not data["choices"]
    ):
        raise ValueError("Облачный API не вернул choices/message.")
    choice = data["choices"][0]
    if not isinstance(choice, dict):
        raise ValueError("Неверная структура облачного choices/message.")
    return {
        "message": choice.get("message"),
        "done": True,
        "done_reason": choice.get("finish_reason", "unknown"),
        "response_model": data.get("model", ""),
    }
