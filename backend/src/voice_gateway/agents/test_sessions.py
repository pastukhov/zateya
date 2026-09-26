import json

import pytest

from .sessions import AgentSessionStore, IdempotencyConflict


def test_cache_history_and_request_ids_are_scoped_to_device(tmp_path):
    store = AgentSessionStore(tmp_path / "llm-sessions.sqlite3")
    store.initialize()
    first = store.begin("one", "same", "hash-a")
    second = store.begin("two", "same", "hash-b")
    assert first.cached is None and second.cached is None
    reply = {"reply": "Сохранила", "note": {"create": True}}
    store.save_result("one", "same", first.generation, reply)
    assert store.begin("one", "same", "hash-a").cached == reply
    with pytest.raises(IdempotencyConflict):
        store.begin("one", "same", "hash-other")
    assert store.begin("two", "same", "hash-b").cached is None
    store.record_turn("one", "same", "Идея", "Сохранила")
    store.record_turn("one", "same", "Идея", "Сохранила")
    assert store.history("one") == [{"role": "user", "content": "Идея"},
                                      {"role": "assistant", "content": "Сохранила"}]


def test_reset_advances_generation_and_old_results_cannot_enter_history(tmp_path):
    store = AgentSessionStore(tmp_path / "db.sqlite3")
    store.initialize()
    old = store.begin("device", "r1", "hash")
    store.save_result("device", "r1", old.generation, {"reply": "old"})
    new_generation = store.reset("device")
    assert new_generation == old.generation + 1
    assert not store.record_turn("device", "r1", "Старая идея", "old", old.generation)
    new = store.begin("device", "r1", "hash")
    assert new.generation == new_generation and new.cached is None
    assert store.history("device") == []


def test_history_limits_and_database_permissions(tmp_path):
    store = AgentSessionStore(tmp_path / "db.sqlite3", history_turns=2, history_max_chars=20)
    store.initialize()
    for index in range(4):
        item = store.begin("d", f"r{index}", f"h{index}")
        store.save_result("d", f"r{index}", item.generation, {"reply": f"a{index}"})
        store.record_turn("d", f"r{index}", f"u{index}", f"a{index}")
    assert store.history("d") == [
        {"role": "user", "content": "u2"}, {"role": "assistant", "content": "a2"},
        {"role": "user", "content": "u3"}, {"role": "assistant", "content": "a3"},
    ]
    assert (tmp_path / "db.sqlite3").stat().st_mode & 0o777 == 0o600


def test_history_is_durable_and_failed_generation_is_not_a_turn(tmp_path):
    path = tmp_path / "db.sqlite3"
    store = AgentSessionStore(path)
    store.initialize()
    store.begin("d", "failed", "h")
    store.begin("d", "ok", "h2")
    store.record_turn("d", "ok", "question", "answer")
    reopened = AgentSessionStore(path)
    assert reopened.history("d") == [{"role": "user", "content": "question"},
                                       {"role": "assistant", "content": "answer"}]
