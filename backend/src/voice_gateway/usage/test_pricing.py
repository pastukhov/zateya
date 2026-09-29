import json
from decimal import Decimal

import pytest

from backend.src.voice_gateway.usage.models import UsageObservation
from backend.src.voice_gateway.usage.pricing import PricingError, load_rates, price_usage


def _rates(*items):
    return {"version": 1, "rates": list(items)}


def _rate(unit, price, *, stage="llm", model="model-a", currency="RUB"):
    return {"stage": stage, "model": model, "currency": currency,
            "unit": unit, "price": price}


def test_prices_input_and_output_tokens_per_million():
    rates = _rates(_rate("input_tokens_1m", "1"), _rate("output_tokens_1m", "2"))
    usage = UsageObservation(input_tokens=1000, output_tokens=500)

    assert price_usage("llm", "model-a", usage, rates).amount == Decimal("0.002")


def test_prices_audio_by_minute():
    rates = _rates(_rate("audio_minute", "0.01", stage="stt"))

    cost = price_usage("stt", "model-a", UsageObservation(audio_seconds=Decimal("30")), rates)

    assert cost.amount == Decimal("0.005")


def test_reported_cost_has_priority_over_estimate():
    usage = UsageObservation(
        input_tokens=1000,
        output_tokens=500,
        reported_amount=Decimal("7.50"),
        reported_currency="RUB",
    )

    cost = price_usage("llm", "model-a", usage, _rates(_rate("input_tokens_1m", "1")))

    assert cost.amount == Decimal("7.50")
    assert cost.currency == "RUB"
    assert cost.kind == "reported"


def test_missing_required_usage_is_unknown_not_partial_price():
    rates = _rates(_rate("input_tokens_1m", "1"), _rate("output_tokens_1m", "2"))

    cost = price_usage("llm", "model-a", UsageObservation(input_tokens=1000), rates)

    assert cost.amount is None
    assert cost.currency is None
    assert cost.kind == "unknown"


def test_explicit_zero_is_a_known_cost():
    cost = price_usage(
        "llm", "model-a",
        UsageObservation(reported_amount=Decimal("0"), reported_currency="RUB"),
        _rates(),
    )

    assert cost.amount == 0
    assert cost.kind == "reported"


@pytest.mark.parametrize("bad", ["-1", "NaN", "Infinity", True])
def test_invalid_rate_price_is_rejected(tmp_path, bad):
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(_rates(_rate("input_tokens_1m", bad))))

    with pytest.raises(PricingError):
        load_rates(path)


def test_unknown_unit_is_rejected(tmp_path):
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps(_rates(_rate("request", "1"))))

    with pytest.raises(PricingError):
        load_rates(path)


def test_mixed_currencies_are_unknown():
    rates = _rates(
        _rate("input_tokens_1m", "1", currency="RUB"),
        _rate("output_tokens_1m", "2", currency="USD"),
    )

    cost = price_usage(
        "llm", "model-a", UsageObservation(input_tokens=1000, output_tokens=500), rates
    )

    assert cost.kind == "unknown"
