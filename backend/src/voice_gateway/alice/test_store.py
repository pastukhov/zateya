import asyncio
import json
from pathlib import Path

import pytest

from backend.src.voice_gateway.alice.models import AliceEvent, AliceReply
from backend.src.voice_gateway.alice.store import (
    AliceStore,
    DraftOverflow,
    EventConflict,
    QueueFull,
)
from backend.src.voice_gateway.text_turns import TextTurnRequest, TextTurnResult


def make_event(number=1, action="new_idea", text="запиши мысль про полив", owner="owner-1", **overrides):
    values = dict(
        owner=owner,
        context_id="mic",
        skill_id="skill-1",
        session_id=f"session-{number}",
        message_id=f"message-{number}",
        payload_hash="",
        action=action,
        text=text,
        archive_dir=str(Path("/tmp/archive/alice")),
    )
    values.update(overrides)
    return AliceEvent(**values)


def make_store(tmp_path):
    store = AliceStore(tmp_path / "alice.sqlite3")
    store.initialize()
    return store


def test_accept_is_atomic_and_replay_returns_same_reply(tmp_path):
    store = make_store(tmp_path)
    reply = AliceReply(text="Приняла мысль в обработку.")
    first = store.accept(make_event(), reply)
    assert first.text == "Приняла мысль в обработку."
    # Replay: same key, same payload → the stored reply, no second job.
    again = store.accept(make_event(), AliceReply(text="другой ответ"))
    assert again.text == "Приняла мысль в обработку."
    assert store.pending_count("owner-1") == 1


def test_same_key_with_different_payload_is_rejected(tmp_path):
    store = make_store(tmp_path)
    store.accept(make_event(), AliceReply(text="ok"))
    with pytest.raises(EventConflict):
        store.accept(make_event(text="другая мысль"), AliceReply(text="ok"))


def test_finish_creates_one_job_and_closes_draft_atomically(tmp_path):
    store = make_store(tmp_path)
    store.accept(make_event(1, "start_draft", ""), AliceReply(text="Запись начата."))
    store.accept(make_event(2, "append_draft", "первый фрагмент"), AliceReply(text="Приняла."))
    store.accept(make_event(3, "append_draft", "второй фрагмент"), AliceReply(text="Приняла."))
    store.accept(make_event(4, "finish_draft", ""), AliceReply(text="Запись закончена."))
    state = store.draft_state("owner-1")
    assert state is None
    assert store.pending_count("owner-1") == 1
    job = store.claim_next()
    assert job is not None
    assert job.request.transcript == "первый фрагмент\nвторой фрагмент"
    assert job.request.channel == "alice"
    assert job.request.request_id.startswith("alice:")
    # Duplicated finish does not create a second job.
    store.accept(make_event(4, "finish_draft", ""), AliceReply(text="повтор"))
    store.accept(make_event(9, "finish_draft", ""), AliceReply(text="нечего закрывать"))
    assert store.pending_count("owner-1") == 1


def test_empty_draft_finish_creates_no_job(tmp_path):
    store = make_store(tmp_path)
    store.accept(make_event(1, "start_draft", ""), AliceReply(text="начали"))
    store.accept(make_event(2, "finish_draft", ""), AliceReply(text="пусто"))
    assert store.pending_count("owner-1") == 0


def test_draft_overflow_refuses_fragment_without_truncation(tmp_path):
    store = make_store(tmp_path)
    store.accept(make_event(1, "start_draft", ""), AliceReply(text="начали"))
    store.accept(make_event(2, "append_draft", "a" * 11_990), AliceReply(text="ok"))
    with pytest.raises(DraftOverflow):
        store.accept(make_event(3, "append_draft", "b" * 20), AliceReply(text="ok"))
    # The draft keeps its previous text intact.
    assert len(store.draft_state("owner-1")["text"]) == 11_990


def test_queue_overflow_is_bounded(tmp_path):
    store = make_store(tmp_path)
    for number in range(8):
        store.accept(make_event(number + 1, "new_idea", f"мысль {number}"), AliceReply(text="ok"))
    assert store.pending_count("owner-1") == 8
    store.accept(make_event(201, "start_draft", ""), AliceReply(text="начали"))
    store.accept(make_event(202, "append_draft", "текст"), AliceReply(text="ok"))
    with pytest.raises(QueueFull):
        store.accept(make_event(203, "finish_draft", ""), AliceReply(text="конец"))


def test_busy_database_times_out_fast_on_webhook_path(tmp_path, monkeypatch):
    store = make_store(tmp_path)
    store.accept(make_event(), AliceReply(text="ok"))
    # Simulate a busy database: an exclusive write lock held by another
    # connection. Webhook-path writes must fail fast, not hang.
    import sqlite3
    import time
    blocker = sqlite3.connect(tmp_path / "alice.sqlite3", isolation_level=None)
    blocker.execute("PRAGMA busy_timeout = 10000")
    blocker.execute("BEGIN EXCLUSIVE")
    started = time.monotonic()
    with pytest.raises(sqlite3.OperationalError):
        store.accept(make_event(2, "new_idea", "вторая"), AliceReply(text="ok"))
    elapsed = time.monotonic() - started
    blocker.close()
    assert elapsed < 2.0  # webhook budget is 2 s total


def test_worker_recovery_returns_running_jobs_to_queue(tmp_path):
    store = make_store(tmp_path)
    store.accept(make_event(), AliceReply(text="ok"))
    job = store.claim_next()
    assert job.status == "running"
    # Crash: no complete/fail. After restart the same job is re-claimed.
    store.recover_running()
    again = store.claim_next()
    assert again is not None
    assert again.job_id == job.job_id
    assert again.request.request_id == job.request.request_id


def test_complete_and_fail_store_results(tmp_path):
    store = make_store(tmp_path)
    store.accept(make_event(), AliceReply(text="ok"))
    job = store.claim_next()
    result = TextTurnResult(reply="Готово", note=None, receipt={"reply": "Готово"},
                            provider="codex", model="m1")
    store.complete(job.job_id, result)
    assert store.latest_reply("owner-1")["status"] == "done"
    assert store.latest_reply("owner-1")["reply"] == "Готово"

    store.accept(make_event(2, action="new_idea", text="вторая"), AliceReply(text="ok"))
    job2 = store.claim_next()
    store.fail(job2.job_id, "agent_timeout")
    latest = store.latest_reply("owner-1")
    assert latest["status"] == "failed"
    assert latest["error"] == "agent_timeout"


def test_long_reply_advances_once_per_idempotent_next_event(tmp_path):
    store = make_store(tmp_path)
    store.accept(make_event(), AliceReply(text="принято"))
    job = store.claim_next()
    first_page = "А" * 850
    second_page = "Б" * 100
    store.complete(job.job_id, TextTurnResult(reply=f"{first_page}. {second_page}", note=None,
                                              receipt=None, provider="p", model=None))
    event = make_event(2, action="next_reply", text="дальше")
    first = store.accept(event, AliceReply(text="продолжаю"))
    replay = store.accept(event, AliceReply(text="не тот ответ"))
    assert first.text == second_page
    assert replay.text == second_page
    assert store.reply_page("owner-1") == (1, 2)


def test_ongoing_status_counts_queued_and_running(tmp_path):
    store = make_store(tmp_path)
    store.accept(make_event(1, "new_idea", "мысль один"), AliceReply(text="ok"))
    store.accept(make_event(2, "new_idea", "мысль два"), AliceReply(text="ok"))
    assert store.pending_count("owner-1") == 2
    job = store.claim_next()
    assert store.pending_count("owner-1") == 2  # running still pending
    store.complete(job.job_id, TextTurnResult(reply="r", note=None, receipt=None,
                                              provider="p", model=None))
    assert store.pending_count("owner-1") == 1


def test_requests_do_not_contain_tokens(tmp_path):
    store = make_store(tmp_path)
    store.accept(make_event(), AliceReply(text="ok"))
    job = store.claim_next()
    encoded = json.dumps(job.request, ensure_ascii=False, default=str)
    assert "oauth" not in encoded.lower()
    assert "token" not in encoded.lower()
