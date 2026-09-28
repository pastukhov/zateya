from backend.src.voice_gateway.alice.dialogue import (
    COMMANDS,
    route_utterance,
    VERBATIM_PREFIX,
)
from backend.src.voice_gateway.alice.models import (
    ACTION_APPEND_DRAFT,
    ACTION_FINISH_DRAFT,
    ACTION_HELP,
    ACTION_NEW_IDEA,
    ACTION_PING,
    ACTION_START_DRAFT,
    ACTION_STATUS,
    ACTION_VERBATIM,
    AliceEvent,
)
from backend.src.voice_gateway.alice.store import AliceStore


class FakeStatusStore:
    """Minimal store surface used by dialogue routing tests."""

    def __init__(self, pending=0, latest=None):
        self._pending = pending
        self._latest = latest

    def pending_count(self, owner):
        return self._pending

    def latest_reply(self, owner):
        return self._latest

    def draft_state(self, owner):
        return None


def envelope(text, screen=False):
    return {
        "meta": {"interfaces": {"screen": screen}},
        "request": {"command": text.lower(), "original_utterance": text},
        "session": {"skill_id": "s", "session_id": "sess", "message_id": "m-1"},
        "version": "1.0",
    }


def test_service_commands_route_without_llm():
    for phrase, action in (
        ("помощь", ACTION_HELP),
        ("проверка связи", ACTION_PING),
        ("начни запись", ACTION_START_DRAFT),
        ("закончи запись", ACTION_FINISH_DRAFT),
        ("готово?", ACTION_STATUS),
        ("Готово", ACTION_STATUS),
    ):
        routed = route_utterance(envelope(phrase), store=FakeStatusStore(), owner="o")
        assert routed.action == action, phrase


def test_greeting_does_not_create_idea():
    routed = route_utterance(envelope("Алиса, запусти навык Моя затея"), store=FakeStatusStore(), owner="o")
    assert routed.action == "greeting"
    assert "Моя затея" in routed.reply.text


def test_content_phrase_becomes_new_idea():
    routed = route_utterance(envelope("Запиши мысль: поливать огород по утрам"),
                             store=FakeStatusStore(), owner="o")
    assert routed.action == ACTION_NEW_IDEA
    assert "Приняла запись" in routed.reply.text


def test_done_word_inside_thought_does_not_finish_draft():
    routed = route_utterance(envelope("Когда всё готово проверить счётчики воды"),
                             store=FakeStatusStore(), owner="o")
    assert routed.action == ACTION_NEW_IDEA


def test_verbatim_prefix_captures_literal_remainder():
    routed = route_utterance(envelope(f"{VERBATIM_PREFIX} закончи запись, потом проверка связи"),
                             store=FakeStatusStore(), owner="o")
    assert routed.action == ACTION_VERBATIM
    assert routed.transcript == "закончи запись, потом проверка связи"


def test_dialogue_collects_all_fragments_until_finish(tmp_path):
    store = AliceStore(tmp_path / "alice.sqlite3")
    store.initialize()

    for number, text in enumerate(("начни запись", "мысль первая", "готово?",
                                   "мысль вторая", "закончи запись"), start=1):
        request = envelope(text)
        request["session"]["session_id"] = "one-session"
        request["session"]["message_id"] = number
        action = route_utterance(request, store=store, owner="owner-1")
        event = AliceEvent(owner="owner-1", context_id="mic", skill_id="s",
                           session_id="one-session", message_id=str(number),
                           payload_hash="", action=action.action,
                           text=action.transcript if action.transcript is not None else text)
        store.accept(event, action.reply)

    assert store.pending_count("owner-1") == 1
    job = store.claim_next()
    assert job.request.transcript == "мысль первая\nготово?\nмысль вторая"


def test_cancel_confirmation_is_persisted_per_owner(tmp_path):
    store = AliceStore(tmp_path / "alice.sqlite3")
    store.initialize()

    def send(number, owner, text):
        request = envelope(text)
        request["session"]["session_id"] = f"session-{owner}"
        request["session"]["message_id"] = number
        action = route_utterance(request, store=store, owner=owner)
        event = AliceEvent(owner=owner, context_id="mic", skill_id="s",
                           session_id=f"session-{owner}", message_id=str(number),
                           payload_hash="", action=action.action,
                           text=action.transcript if action.transcript is not None else text)
        return store.accept(event, action.reply)

    send(1, "owner-1", "начни запись")
    send(2, "owner-1", "отмена")
    send(1, "owner-2", "начни запись")
    send(2, "owner-2", "да")
    assert store.draft_state("owner-2")["text"] == "да"
    send(3, "owner-1", "да")
    assert store.draft_state("owner-1") is None
    assert store.draft_state("owner-2")["text"] == "да"


def test_status_reports_processing_without_regeneration():
    store = FakeStatusStore(pending=2)
    routed = route_utterance(envelope("Готово?"), store=store, owner="o")
    assert routed.action == ACTION_STATUS
    assert "обрабатываю" in routed.reply.text.lower()


def test_status_reports_done_reply():
    store = FakeStatusStore(latest={"status": "done", "reply": "Сохранила мысль «Полив».", "error": None})
    routed = route_utterance(envelope("Готово?"), store=store, owner="o")
    assert "Сохранила мысль «Полив»" in routed.reply.text


def test_status_reports_failure_honestly():
    store = FakeStatusStore(latest={"status": "failed", "reply": None, "error": "agent_timeout"})
    routed = route_utterance(envelope("Готово?"), store=store, owner="o")
    assert "Не получилось" in routed.reply.text


def test_cancel_requires_confirmation():
    store = FakeStatusStore()
    ask = route_utterance(envelope("Отмена"), store=store, owner="o")
    assert ask.action == "noop"
    assert "Нет активного" in ask.reply.text


def test_exit_keeps_state_message():
    routed = route_utterance(envelope("выйти"), store=FakeStatusStore(), owner="o")
    assert routed.reply.end_session is True
    assert "сохранены" in routed.reply.text


def test_screen_and_voice_get_same_content():
    voice = route_utterance(envelope("помощь", screen=False), store=FakeStatusStore(), owner="o")
    screen = route_utterance(envelope("помощь", screen=True), store=FakeStatusStore(), owner="o")
    assert voice.reply.text == screen.reply.text


def test_commands_are_exact_matches_only():
    assert "готово?" in COMMANDS
    assert "давай готово уже" not in COMMANDS
