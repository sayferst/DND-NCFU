"""Fail-closed price/capability contracts and nonsecret visual preferences."""

import json
from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal
from pathlib import Path

from rpg_vkr.narrative.routerai import _data, amount
from rpg_vkr.ui.workspace_tools import atomic_text

RECRAFT = "recraft/recraft-v4.1-flash"
FLUX = "black-forest-labs/flux-3-image-klein"
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
            or not 0 < self.economy_cap <= 850000
            or type(self.quality_cap) is not int
            or not 0 < self.quality_cap <= 5000000
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


def route(category, common, references):
    return RECRAFT if category == "items" and common and not references else FLUX


def quote_model(catalog, model, size, reference_count=0):
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
    if not isinstance(parameters, list) or "size" not in parameters:
        raise ValueError("Каталог не подтверждает параметр size. Нужен контракт Images API.")
    limits = row.get("per_request_limits") or {}
    if not isinstance(limits, dict):
        raise ValueError("Неизвестные ограничения модели.")
    supported = limits.get("supported_resolutions")
    if not isinstance(supported, list) or not any(s in supported for s in (size, SIZES[size])):
        raise ValueError("Выбранное разрешение не подтверждено каталогом.")
    cap = limits.get("max_input_references", 0)
    if type(cap) is not int or not 0 <= cap <= 32:
        raise ValueError("Неизвестен лимит референсов.")
    supports = model == FLUX and "input_references" in parameters and cap > 0
    if reference_count and (not supports or reference_count > cap):
        raise ValueError("Каталог не подтверждает нужное количество input_references.")
    total = None
    variants = row.get("image_pricing", [])
    if variants and not isinstance(variants, list):
        raise ValueError("Неизвестный тариф вариантов.")
    exact = [
        r
        for r in variants
        if isinstance(r, dict)
        and r.get("unit") == "image"
        and r.get("variant") in (size, SIZES[size])
    ]
    generic = [
        r
        for r in variants
        if isinstance(r, dict) and r.get("unit") == "image" and r.get("variant") is None
    ]
    choices = exact or generic
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
    return ImageQuote(model, size, total, cap, supports)


def payload(quote, prompt, references=()):
    if not isinstance(prompt, str) or not 1 <= len(prompt) <= 16000:
        raise ValueError("Некорректное визуальное описание.")
    if len(references) > quote.reference_limit or references and not quote.supports_references:
        raise ValueError("Референсы не разрешены для этой модели.")
    result = {"model": quote.model, "prompt": prompt, "n": 1, "size": SIZES[quote.size]}
    if references:
        if quote.model != FLUX:
            raise ValueError("Recraft принимает только текст.")
        result["input_references"] = list(references)
    return result
