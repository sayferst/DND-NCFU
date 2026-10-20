"""Fail-closed price/capability contracts and nonsecret visual preferences."""

import json
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from rpg_vkr.narrative.routerai import _data, amount
from rpg_vkr.ui.workspace_tools import atomic_text

RECRAFT = "recraft/recraft-v4.1-flash"
FLUX = "black-forest-labs/flux-3-image-klein"
PRICE_LIMITS = {RECRAFT: 5_000_000, FLUX: 10_000_000}
SIZES = {
    "768": "768x768",
    "1K": "1024x1024",
    "1.5K": "1536x1536",
    "2K": "2048x2048",
    "4K": "4096x4096",
}


def micros(value):
    return int((amount(value) * 1000000).to_integral_value(rounding=ROUND_CEILING))


def rub(value):
    return f"{Decimal(value) / 1000000:.4f} ₽"


@dataclass(frozen=True)
class VisualSettings:
    monthly_micros: int = 0
    economy_cap: int = 850000
    quality_cap: int = 5000000
    portrait_size: str = "1K"
    scene_size: str = "1K"
    confirm: bool = True
    consent: bool = False

    def __post_init__(self):
        if (
            type(self.monthly_micros) is not int
            or not 0 <= self.monthly_micros <= 2000000000
            or type(self.economy_cap) is not int
            or not 0 < self.economy_cap <= PRICE_LIMITS[RECRAFT]
            or type(self.quality_cap) is not int
            or not 0 < self.quality_cap <= PRICE_LIMITS[FLUX]
            or type(self.confirm) is not bool
            or type(self.consent) is not bool
            or self.portrait_size not in SIZES
            or self.scene_size not in SIZES
        ):
            raise ValueError("Некорректные настройки изображений.")

    @classmethod
    def load(cls, path):
        try:
            path = Path(path)
            if path.stat().st_size > 4096:
                return cls()
            return cls(**json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path):
        atomic_text(Path(path), json.dumps(asdict(self), ensure_ascii=False, indent=2) + "\n")


@dataclass(frozen=True)
class ImageQuote:
    model: str
    size: str
    total: int
    reference_limit: int
    supports_references: bool
    size_parameter: str = "size"

    @property
    def size_description(self):
        return self.size if self.size_parameter else "по умолчанию модели (размер не задан)"


def route(category, economy_eligible, references):
    return RECRAFT if category == "items" and economy_eligible and not references else FLUX


def route_reason(category, economy_eligible, references):
    if references:
        return "Есть прежние изображения: FLUX сохраняет визуальную идентичность."
    if category == "items" and economy_eligible:
        return "Обычный предмет без референсов: экономичная Recraft."
    return "Персонаж, существо, локация, событие или уникальный объект: качественная FLUX."


def _resolution_matches(value, size):
    # RouterAI publishes e.g. supported_image_sizes="1K", image_pricing.variant="1k".
    # Normalize spelling only: quality tiers and other dimensions remain distinct.
    return isinstance(value, str) and value.strip().casefold() in (
        size.casefold(),
        SIZES[size].casefold(),
    )


def quote_model(catalog, model, size, reference_count=0):
    if model not in {RECRAFT, FLUX} or size not in SIZES:
        raise ValueError("Неизвестная модель или разрешение изображений.")
    if type(reference_count) is not int or not 0 <= reference_count <= 32:
        raise ValueError("Некорректное количество референсов.")
    rows = _data(catalog)
    if not isinstance(rows, list):
        raise ValueError("Каталог изображений имеет неизвестный формат.")
    candidates = [r for r in rows if isinstance(r, dict) and r.get("id") == model]
    if len(candidates) != 1:
        raise ValueError("Точная модель не найдена в актуальном каталоге.")
    row = candidates[0]
    prices, units = row.get("pricing", {}), row.get("pricing_units", {})
    if not isinstance(prices, dict) or not isinstance(units, dict):
        raise ValueError("Неизвестная цена.")
    parameters = row.get("supported_parameters", [])
    if parameters is None:
        parameters = []
    if not isinstance(parameters, list):
        raise ValueError("Неизвестный формат параметров модели.")
    size_parameter = (
        "resolution" if "resolution" in parameters else "size" if "size" in parameters else ""
    )
    limits = row.get("per_request_limits", {})
    if limits is None:
        limits = {}
    if not isinstance(limits, dict):
        raise ValueError("Неизвестные ограничения модели.")
    for supported in (limits.get("supported_resolutions"), row.get("supported_image_sizes")):
        if supported is not None and (
            not isinstance(supported, list)
            or not any(_resolution_matches(value, size) for value in supported)
        ):
            raise ValueError("Выбранное разрешение не подтверждено каталогом.")
    count = row.get("max_image_count")
    if count is not None and (type(count) is not int or count < 1):
        raise ValueError("Каталог не разрешает создать одно изображение.")
    # Current catalog uses top-level fields; older responses nested limits.
    # Both are authoritative when present. Never discard a stricter restriction.
    caps = [
        value
        for value in (limits.get("max_input_references"), row.get("max_image_references"))
        if value is not None
    ]
    if any(type(value) is not int or not 0 <= value <= 32 for value in caps):
        raise ValueError("Неизвестен лимит референсов.")
    cap = min(caps) if caps else (1 if model == FLUX else 0)
    advertised = row.get("supported_image_references")
    if advertised is not None and type(advertised) is not bool:
        raise ValueError("Неизвестна поддержка референсов.")
    supports = model == FLUX and cap > 0 and advertised is not False
    if not supports:
        cap = 0
    if reference_count and (not supports or reference_count > cap):
        raise ValueError("Каталог не подтверждает нужное количество input_references.")
    total = None
    variants = row.get("image_pricing", [])
    if variants is None:
        variants = []
    if not isinstance(variants, list):
        raise ValueError("Неизвестный тариф вариантов.")
    exact = [
        r
        for r in variants
        if isinstance(r, dict)
        and r.get("unit") == "image"
        and _resolution_matches(r.get("variant"), size)
    ]
    # A priced resolution variant is model-specific evidence too. The Images
    # guide defines both transports; supported_parameters need not repeat them.
    if not size_parameter and len(exact) == 1:
        size_parameter = (
            "resolution" if exact[0]["variant"].strip().casefold() == size.casefold() else "size"
        )
    if not size_parameter and (
        size != "1K" or any(isinstance(r, dict) and r.get("variant") is not None for r in variants)
    ):
        raise ValueError(
            "Нельзя подтвердить выбранный размер и его цену: в каталоге нет "
            "size/resolution или подходящего тарифа разрешения."
        )
    generic = [
        r
        for r in variants
        if isinstance(r, dict) and r.get("unit") == "image" and r.get("variant") is None
    ]
    choices = exact or generic
    if len(choices) > 1 or variants and not choices:
        raise ValueError(
            f"Полная цена изображения {size} "
            + ("неоднозначна: несколько тарифов." if len(choices) > 1 else "не найдена в каталоге.")
            + " Обновите модели в панели «Художник». Платный запрос не отправлен."
        )
    if len(choices) == 1:
        total = micros(choices[0].get("price"))
    elif units.get("image_output") == "image":
        total = micros(prices.get("image_output"))
    if total is None or total <= 0:
        raise ValueError("Полная цена изображения неизвестна; запрос запрещён.")
    for name, value in prices.items():
        if name == "image_output":
            continue
        price = amount(value)
        if price == 0:
            continue
        if name == "request" and units.get(name) == "request":
            total += micros(price)
        else:
            raise ValueError("Есть дополнительные расходы без проверенного полного расчёта.")
    return ImageQuote(model, size, total, cap, supports, size_parameter)


def payload(quote, prompt, references=()):
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 16000:
        raise ValueError("Некорректное визуальное описание.")
    if len(references) > quote.reference_limit or references and not quote.supports_references:
        raise ValueError("Референсы не разрешены для этой модели.")
    result = {"model": quote.model, "prompt": prompt, "n": 1}
    if quote.model == RECRAFT:
        # Exact model-page example: Recraft accepts a square aspect_ratio,
        # including the minimal request without a size control.
        result["aspect_ratio"] = "1:1"
    if quote.size_parameter:
        result[quote.size_parameter] = (
            SIZES[quote.size] if quote.size_parameter == "size" else quote.size
        )
    if references:
        if quote.model != FLUX:
            raise ValueError("Recraft принимает только текст.")
        result["input_references"] = [
            {"type": "image_url", "image_url": {"url": reference}} for reference in references
        ]
    return result
