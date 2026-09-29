from decimal import Decimal

from prometheus_client import CollectorRegistry, generate_latest

from .collector import UsageCollector
from .models import CallContext, Cost, UsageObservation
from .store import UsageStore


def test_collector_exports_provider_and_completed_note_totals(tmp_path):
    store = UsageStore(tmp_path / "usage.sqlite3")
    store.initialize()
    call_id = store.begin_call(CallContext("turn-1", "alice", "llm", "cheap-model"))
    store.finish_call(
        call_id,
        outcome="success",
        elapsed_seconds=0.4,
        usage=UsageObservation(input_tokens=10, output_tokens=5),
        cost=Cost(Decimal("0.012"), "RUB", "estimated"),
    )
    store.finish_turn("turn-1", channel="alice", outcome="success",
                      operation="capture", note_saved=True)

    registry = CollectorRegistry()
    registry.register(UsageCollector(store))
    body = generate_latest(registry).decode()

    assert 'zateya_turns_total{channel="alice",outcome="success"} 1.0' in body
    assert 'zateya_notes_total{channel="alice",operation="capture"} 1.0' in body
    assert ('zateya_provider_cost_total{channel="alice",cost_kind="estimated",'
            'currency="RUB",model="cheap-model",stage="llm"} 0.012') in body
    assert ('zateya_usage_tokens_total{channel="alice",direction="input",'
            'model="cheap-model",stage="llm"} 10.0') in body
    assert ('zateya_completed_note_cost_total{channel="alice",cost_kind="estimated",'
            'currency="RUB"} 0.012') in body
    assert ('zateya_completed_notes_costed_total{channel="alice",cost_kind="estimated",'
            'currency="RUB"} 1.0') in body


def test_collector_excludes_incomplete_note_cost_and_counts_unknown_usage(tmp_path):
    store = UsageStore(tmp_path / "usage.sqlite3")
    store.initialize()
    store.begin_call(CallContext("turn-2", "recorder", "tts", "speech-model"))
    store.initialize()  # restart classifies the unfinished attempt as unknown
    store.finish_turn("turn-2", channel="recorder", outcome="error",
                      operation="capture", note_saved=True)

    registry = CollectorRegistry()
    registry.register(UsageCollector(store))
    body = generate_latest(registry).decode()

    assert ('zateya_usage_unknown_total{channel="recorder",model="speech-model",'
            'stage="tts"} 1.0') in body
    assert ('zateya_completed_note_cost_excluded_total{channel="recorder",'
            'reason="incomplete_usage"} 1.0') in body
    assert 'zateya_completed_note_cost_total{channel="recorder"' not in body


def test_pending_turn_is_hidden_until_terminal_and_query_is_visible_as_operation(tmp_path):
    store = UsageStore(tmp_path / "usage.sqlite3")
    store.initialize()
    store.finish_turn("turn-query", channel="alice", outcome="pending",
                      operation="query", note_saved=False)
    registry = CollectorRegistry()
    registry.register(UsageCollector(store))
    pending = generate_latest(registry).decode()
    assert 'zateya_turns_total{channel="alice"' not in pending
    assert 'zateya_operations_total{channel="alice"' not in pending

    store.finish_turn("turn-query", channel="alice", outcome="success",
                      operation="none", note_saved=False)
    terminal = generate_latest(registry).decode()
    assert 'zateya_turns_total{channel="alice",outcome="success"} 1.0' in terminal
    assert 'zateya_operations_total{channel="alice",operation="query"} 1.0' in terminal
