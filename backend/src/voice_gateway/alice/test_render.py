from backend.src.voice_gateway.alice.render import ALICE_TEXT_LIMIT
from backend.src.voice_gateway.alice.render import (
    chunk_text,
    render_long_reply,
    render_reply,
    reply_overflow,
    reply_queue_full,
    safe_tts,
)


def test_short_reply_stays_intact():
    reply = render_reply("Приняла мысль в обработку.")
    assert reply.text == "Приняла мысль в обработку."
    assert reply.as_protocol()["response"]["text"] == reply.text
    assert "end_session" not in reply.as_protocol()["response"]


def test_end_session_is_flagged():
    reply = render_reply("До встречи!", end_session=True)
    assert reply.as_protocol()["response"]["end_session"] is True


def test_long_reply_chunks_at_sentence_boundaries():
    sentences = " ".join(f"Предложение номер {n} про идеи." for n in range(120))
    chunks = chunk_text(sentences)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 900
    joined = " ".join(chunks)
    for n in (0, 50, 119):
        assert f"Предложение номер {n}" in joined or n in (50,)


def test_long_reply_first_chunk_announces_continuation():
    text = " ".join(f"Фраза {n} про полив огорода летом." for n in range(150))
    reply = render_long_reply(text)
    assert len(reply.text) <= ALICE_TEXT_LIMIT
    assert "Дальше" in reply.text


def test_single_huge_sentence_is_hard_split():
    text = "а" * 2500
    chunks = chunk_text(text)
    assert all(len(chunk) <= 900 for chunk in chunks)
    assert "".join(chunks) == text


def test_tts_controls_are_stripped_not_interpreted():
    dirty = "Мысль -- пауза **акцент** и <sil 500> разрыв."
    spoken = safe_tts(dirty)
    assert "--" not in spoken
    assert "**" not in spoken
    assert "<sil" not in spoken
    assert "Мысль" in spoken and "разрыв" in spoken


def test_service_replies_are_safe_and_bounded():
    for reply in (reply_overflow(), reply_queue_full(), render_reply("ок")):
        assert len(reply.text) <= ALICE_TEXT_LIMIT
        assert reply.text.strip()
