"""Safe reply rendering for the Alice protocol (plan task 5).

``response.text``/``response.tts`` are limited to 1024 characters each
(platform rule). Long answers are split at sentence boundaries into chunks
under 900 characters; the owner asks «Дальше» for the next part. Plain
text answers never treat LLM output as TTS markup: control constructs are
stripped for the ``tts`` field instead of being interpreted.
"""

from __future__ import annotations

import re

from backend.src.voice_gateway.alice.models import AliceReply, DRAFT_MAX_CHARS

#: Platform limit for response.text / response.tts.
ALICE_TEXT_LIMIT = 1024

#: Chunk target below the platform limit (plan task 5).
CHUNK_LIMIT = 900

#: TTS control constructs that must not be interpreted from LLM text.
_TTS_CONTROLS = re.compile(r"[-]{2,}|\*+|sil <[^>]*>|<[^>]+>")


def chunk_text(text: str, limit: int = CHUNK_LIMIT) -> list[str]:
    """Split text into chunks at sentence boundaries, each under ``limit``.

    Never cuts inside a word; a single very long sentence is hard-split.
    """
    text = text.strip()
    if len(text) <= limit:
        return [text] if text else [""]
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > limit:
            # A single sentence longer than the limit: hard-split it.
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:limit])
            sentence = sentence[limit:]
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > limit and current:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def safe_tts(text: str) -> str:
    """Strip control constructs so LLM text is spoken literally."""
    return _TTS_CONTROLS.sub(" ", text).strip()


def render_reply(text: str, *, end_session: bool = False) -> AliceReply:
    """One-part reply under the platform limit (dialogue helpers use this)."""
    trimmed = text.strip()
    if len(trimmed) > ALICE_TEXT_LIMIT:
        trimmed = chunk_text(trimmed, CHUNK_LIMIT)[0]
    return AliceReply(text=trimmed, tts=safe_tts(trimmed), end_session=end_session)


def render_long_reply(text: str, *, end_session: bool = False) -> AliceReply:
    """Reply that may continue with «Дальше» when text exceeds one chunk."""
    chunks = chunk_text(text)
    first = chunks[0] if chunks else ""
    more = len(chunks) > 1
    body = first if not more else f"{first}\n(Скажите «Дальше», чтобы продолжить.)"
    return AliceReply(text=body[:ALICE_TEXT_LIMIT], tts=safe_tts(body)[:ALICE_TEXT_LIMIT],
                      end_session=end_session)


def reply_busy() -> AliceReply:
    """Safe answer when the service is overloaded or the store is busy."""
    return render_reply("Сейчас не могу принять запрос. Повторите через минуту.")


def reply_queue_full() -> AliceReply:
    return render_reply("Очередь заполнена: попросите статус «Готово?» и дождитесь обработки.")


def reply_overflow() -> AliceReply:
    return render_reply(
        f"Черновик превысил {DRAFT_MAX_CHARS} символов. Закончите запись или начните новую мысль."
    )
