from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .models import Cost, UsageObservation

SUPPORTED_UNITS = frozenset({
    "input_tokens_1m", "output_tokens_1m", "audio_minute", "text_characters_1m",
})
_JSON_PATH = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*$")


class PricingError(ValueError):
    pass


def load_rates(path: Path | None) -> dict:
    if path is None or not Path(path).is_file():
        return {"version": 1, "rates": [], "reported_costs": []}
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PricingError("invalid pricing file") from exc
    if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("rates"), list):
        raise PricingError("pricing file must use version 1 and a rates list")
    normalized = []
    for rate in data["rates"]:
        if not isinstance(rate, dict) or rate.get("unit") not in SUPPORTED_UNITS:
            raise PricingError("unsupported pricing unit")
        stage, model, currency = rate.get("stage"), rate.get("model"), rate.get("currency")
        if not all(isinstance(value, str) and value for value in (stage, model, currency)):
            raise PricingError("stage, model and currency are required")
        price = _decimal(rate.get("price"))
        if price is None or price < 0:
            raise PricingError("price must be a finite non-negative decimal")
        normalized.append({**rate, "price": price})
    reported_costs = data.get("reported_costs", [])
    if not isinstance(reported_costs, list):
        raise PricingError("reported_costs must be a list")
    normalized_reported = []
    seen = set()
    for item in reported_costs:
        if not isinstance(item, dict):
            raise PricingError("reported cost configuration must be an object")
        stage, model = item.get("stage"), item.get("model")
        amount_path = item.get("amount_path")
        currency, currency_path = item.get("currency"), item.get("currency_path")
        if not all(isinstance(value, str) and value for value in (stage, model)):
            raise PricingError("reported cost stage and model are required")
        if not isinstance(amount_path, str) or not _JSON_PATH.fullmatch(amount_path):
            raise PricingError("reported cost amount_path is invalid")
        if (currency is None) == (currency_path is None):
            raise PricingError("set exactly one of currency and currency_path")
        if currency is not None and (not isinstance(currency, str) or not currency.strip()):
            raise PricingError("reported cost currency is invalid")
        if currency_path is not None and (
            not isinstance(currency_path, str) or not _JSON_PATH.fullmatch(currency_path)
        ):
            raise PricingError("reported cost currency_path is invalid")
        key = (stage, model)
        if key in seen:
            raise PricingError("only one reported cost configuration is allowed per stage and model")
        seen.add(key)
        normalized_reported.append({**item, "currency": currency.strip() if currency else None})
    return {"version": 1, "rates": normalized, "reported_costs": normalized_reported}


def extract_reported_cost(
    stage: str, model: str, payload: dict, pricing: dict
) -> tuple[Decimal | None, str | None]:
    """Extract provider-reported cost using only explicitly configured JSON paths."""
    configurations = [
        item for item in pricing.get("reported_costs", [])
        if item.get("stage") == stage and item.get("model") == model
    ]
    if len(configurations) != 1 or not isinstance(payload, dict):
        return None, None
    configuration = configurations[0]
    amount = _decimal(_path_value(payload, configuration.get("amount_path")))
    if amount is None or amount < 0:
        return None, None
    currency = configuration.get("currency")
    if currency is None:
        currency = _path_value(payload, configuration.get("currency_path"))
    if not isinstance(currency, str) or not currency.strip():
        return None, None
    return amount, currency.strip()


def _path_value(payload: dict, path: object):
    if not isinstance(path, str) or not _JSON_PATH.fullmatch(path):
        return None
    value: object = payload
    for component in path.split("."):
        if not isinstance(value, dict) or component not in value:
            return None
        value = value[component]
    return value


def price_usage(stage: str, model: str, usage: UsageObservation, rates: dict) -> Cost:
    reported = _decimal(usage.reported_amount)
    if reported is not None and reported >= 0 and usage.reported_currency:
        return Cost(reported, usage.reported_currency, "reported")

    matching = [rate for rate in rates.get("rates", [])
                if rate.get("stage") == stage and rate.get("model") == model]
    if not matching:
        return Cost(None, None, "unknown")
    currencies = {rate.get("currency") for rate in matching}
    if len(currencies) != 1 or None in currencies:
        return Cost(None, None, "unknown")

    total = Decimal(0)
    for rate in matching:
        price = _decimal(rate.get("price"))
        if price is None or price < 0 or rate.get("unit") not in SUPPORTED_UNITS:
            return Cost(None, None, "unknown")
        quantity = _quantity(rate["unit"], usage)
        if quantity is None:
            return Cost(None, None, "unknown")
        total += quantity * price
    return Cost(total, next(iter(currencies)), "estimated")


def _quantity(unit: str, usage: UsageObservation) -> Decimal | None:
    if unit == "input_tokens_1m":
        return _count(usage.input_tokens, Decimal(1_000_000))
    if unit == "output_tokens_1m":
        return _count(usage.output_tokens, Decimal(1_000_000))
    if unit == "text_characters_1m":
        return _count(usage.text_characters, Decimal(1_000_000))
    if unit == "audio_minute":
        seconds = _decimal(usage.audio_seconds)
        return None if seconds is None or seconds < 0 else seconds / Decimal(60)
    return None


def _count(value: int | None, divisor: Decimal) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return Decimal(value) / divisor


def _decimal(value) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None
