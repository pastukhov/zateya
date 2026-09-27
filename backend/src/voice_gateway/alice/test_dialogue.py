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
    assert "Приняла мысль" in routed.reply.text


def test_done_word_inside_thought_does_not_finish_draft():
    routed = route_utterance(envelope("Когда всё готово проверить счётчики воды"),
                             store=FakeStatusStore(), owner="o")
    assert routed.action == ACTION_NEW_IDEA


def test_verbatim_prefix_captures_literal_remainder():
    routed = route_utterance(envelope(f"{VERBATIM_PREFIX} закончи запись, потом проверка связи"),
                             store=FakeStatusStore(), owner="o")
    assert routed.action == ACTION_VERBATIM


def test_status_reports_processing_without_regeneration():
    store = FakeStatusStore(pending=2)
    routed = route_utterance(envelope("Готово?"), store=store, owner="o")
    assert routed.action == ACTION_STATUS
    assert "Обрабатываю" in routed.reply.text


def test_status_reports_done_reply():
    store = FakeStatusStore(latest={"status": "done", "reply": "Сохранила мысль «Полив».", "error": None})
    routed = route_utterance(envelope("Готово?"), store=store, owner="o")
    assert "Сохранила мысль «Полив»" in routed.reply.text


def test_status_reports_failure_honestly():
    store = FakeStatusStore(latest={"status": "failed", "reply": None, "error": "agent_timeout"})
    routed = route_utterance(envelope("Готово?"), store=store, owner="o")
    assert "Не получилось" in routed.reply.text


def test_cancel_requires_confirmation():
    ask = route_utterance(envelope("Отмена"), store=FakeStatusStore(), owner="o")
    assert ask.reply.text  # asks for confirmation
    confirm = route_utterance(envelope("да"), store=FakeStatusStore(), owner="o")
    assert confirm.action == "cancel_draft"


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
