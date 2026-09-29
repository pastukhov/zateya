from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from prometheus_client import CollectorRegistry, Counter

from backend.src.voice_gateway.usage.models import CallContext, Cost, UsageObservation
from backend.src.voice_gateway.usage.recorder import UsageRecorder
from backend.src.voice_gateway.usage.store import UsageStore


def _context(turn_id: str = "turn-1") -> CallContext:
    return CallContext(turn_id=turn_id, channel="alice", stage="llm", model="model-a")


def _finish(store: UsageStore, call_id: str, amount: str, currency: str = "USD") -> None:
    store.finish_call(
        call_id,
        outcome="success",
        elapsed_seconds=1.25,
        usage=UsageObservation(input_tokens=100, output_tokens=50),
        cost=Cost(amount=Decimal(amount), currency=currency, kind="estimated"),
    )


def test_reopen_preserves_exact_decimal_cost(tmp_path):
    path = tmp_path / "usage.sqlite3"
    store = UsageStore(path)
    store.initialize()
    call_id = store.begin_call(_context())
    _finish(store, call_id, "0.100000000000000001")

    reopened = UsageStore(path)
    reopened.initialize()

    assert reopened.snapshot()["cost_totals"] == {
        ("alice", "llm", "model-a", "USD", "estimated"): Decimal("0.100000000000000001")
    }


def test_finish_call_is_idempotent(tmp_path):
    store = UsageStore(tmp_path / "usage.sqlite3")
    store.initialize()
    call_id = store.begin_call(_context())
    _finish(store, call_id, "0.01")
    _finish(store, call_id, "99")

    snapshot = store.snapshot()
    assert snapshot["finished_calls"] == 1
    assert next(iter(snapshot["cost_totals"].values())) == Decimal("0.01")


def test_two_physical_attempts_for_one_turn_are_both_counted(tmp_path):
    store = UsageStore(tmp_path / "usage.sqlite3")
    store.initialize()
    for amount in ("0.01", "0.02"):
        call_id = store.begin_call(_context())
        _finish(store, call_id, amount)

    snapshot = store.snapshot()
    assert snapshot["finished_calls"] == 2
    assert next(iter(snapshot["cost_totals"].values())) == Decimal("0.03")


def test_concurrent_writes_are_not_lost(tmp_path):
    store = UsageStore(tmp_path / "usage.sqlite3")
    store.initialize()

    def write(number: int) -> None:
        call_id = store.begin_call(_context(f"turn-{number}"))
        _finish(store, call_id, "0.01")

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(write, range(30)))

    snapshot = store.snapshot()
    assert snapshot["finished_calls"] == 30
    assert next(iter(snapshot["cost_totals"].values())) == Decimal("0.30")


def test_different_currencies_are_never_combined(tmp_path):
    store = UsageStore(tmp_path / "usage.sqlite3")
    store.initialize()
    usd = store.begin_call(_context("usd"))
    rub = store.begin_call(_context("rub"))
    _finish(store, usd, "1.25", "USD")
    _finish(store, rub, "90", "RUB")

    totals = store.snapshot()["cost_totals"]
    assert totals[("alice", "llm", "model-a", "USD", "estimated")] == Decimal("1.25")
    assert totals[("alice", "llm", "model-a", "RUB", "estimated")] == Decimal("90")


def test_started_call_after_reopen_is_unknown_not_free(tmp_path):
    path = tmp_path / "usage.sqlite3"
    store = UsageStore(path)
    store.initialize()
    store.begin_call(_context())

    reopened = UsageStore(path)
    reopened.initialize()

    assert reopened.snapshot()["unknown_calls"] == 1
    assert reopened.snapshot()["cost_totals"] == {}


def test_recorder_does_not_break_caller_when_store_write_fails():
    class BrokenStore:
        def begin_call(self, context):
            raise OSError("secret path must not be logged")

    registry = CollectorRegistry()
    errors = Counter("zateya_usage_write_errors_total", "Usage write errors", registry=registry)
    recorder = UsageRecorder(BrokenStore(), write_errors=errors)

    assert recorder.begin_call(_context()) is None
    assert registry.get_sample_value("zateya_usage_write_errors_total") == 1
    recorder.finish_call(
        None,
        outcome="success",
        elapsed_seconds=0,
        usage=UsageObservation(),
        cost=Cost(amount=None, currency=None, kind="unknown"),
    )
