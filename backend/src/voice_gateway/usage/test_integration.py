from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from prometheus_client import CollectorRegistry, generate_latest

from .collector import UsageCollector
from .models import CallContext, Cost, UsageObservation
from .store import UsageStore


def test_restart_and_concurrent_scrape_preserve_cost_without_leaking_content(tmp_path):
    path = tmp_path / "usage.sqlite3"
    store = UsageStore(path)
    store.initialize()

    def paid(turn, channel, stage, model, amount):
        call = store.begin_call(CallContext(turn, channel, stage, model))
        store.finish_call(call, outcome="success", elapsed_seconds=0.2,
                          usage=UsageObservation(input_tokens=100, output_tokens=20),
                          cost=Cost(Decimal(amount), "RUB", "estimated"))

    paid("recorder-capture", "recorder", "stt", "speech", "0.01")
    paid("recorder-capture", "recorder", "llm", "chat", "0.02")
    paid("recorder-capture", "recorder", "tts", "voice", "0.03")
    store.finish_turn("recorder-capture", channel="recorder", outcome="success",
                      operation="capture", note_saved=True)
    paid("alice-query", "alice", "llm", "chat", "0.02")
    store.finish_turn("alice-query", channel="alice", outcome="success",
                      operation="query", note_saved=False)
    store.begin_call(CallContext("alice-incomplete", "alice", "llm", "chat"))
    store.initialize()  # restart recovers the unfinished call as unknown

    registry = CollectorRegistry()
    registry.register(UsageCollector(store))
    with ThreadPoolExecutor(max_workers=4) as pool:
        scrapes = list(pool.map(lambda _: generate_latest(registry).decode(), range(8)))

    snapshot = UsageStore(path).snapshot()
    assert snapshot["cost_totals"][("recorder", "llm", "chat", "RUB", "estimated")] == Decimal("0.02")
    assert snapshot["cost_totals"][("alice", "llm", "chat", "RUB", "estimated")] == Decimal("0.02")
    for body in scrapes:
        assert "recorder-capture" not in body
        assert "alice-query" not in body
        assert "zateya_completed_notes_costed_total" in body
        assert "zateya_usage_unknown_total" in body
