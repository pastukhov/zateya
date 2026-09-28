"""Deterministic dialogue routing before any LLM work (plan task 5).

Control commands are recognized as whole utterances only; the word
«готово» inside a thought never finishes a draft. Content lives in
``original_utterance``; intents are used solely for built-in commands
(помощь, статус, выход). No LLM is called for service commands.

Actions map onto the store's transitions from task 3:
- new_idea / verbatim: create one job from the whole utterance;
- start_draft / append_draft / finish_draft / cancel_draft: multi-utterance
  dictation with a durable draft;
- status: report pending/last result without regenerating;
- help / ping: fixed answers.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.src.voice_gateway.alice.models import (
    ACTION_APPEND_DRAFT,
    ACTION_CANCEL_DRAFT,
    ACTION_CANCEL_REQUEST,
    ACTION_CONFIRM_CANCEL,
    ACTION_DECLINE_CANCEL,
    ACTION_FINISH_DRAFT,
    ACTION_HELP,
    ACTION_NEW_IDEA,
    ACTION_PING,
    ACTION_START_DRAFT,
    ACTION_RESUME_DRAFT,
    ACTION_NOOP,
    ACTION_NEXT_REPLY,
    ACTION_STATUS,
    ACTION_VERBATIM,
    AliceReply,
)
from backend.src.voice_gateway.alice.render import render_reply

#: Whole-utterance control commands (normalized: lowercased, punctuation stripped).
COMMANDS = {
    "начни запись": ACTION_START_DRAFT,
    "продолжи запись": ACTION_START_DRAFT,
    "закончи запись": ACTION_FINISH_DRAFT,
    "запись окончена": ACTION_FINISH_DRAFT,
    "отмени черновик": ACTION_CANCEL_DRAFT,
    "помощь": ACTION_HELP,
    "что ты умеешь": ACTION_HELP,
    "готово": ACTION_STATUS,
    "готово?": ACTION_STATUS,
    "статус": ACTION_STATUS,
    "проверка связи": ACTION_PING,
    "пинг": ACTION_PING,
    "дальше": ACTION_NEXT_REPLY,
}

#: Prefix that records the remainder as literal content.
VERBATIM_PREFIX = "запиши дословно:"

#: Confirmation word required for draft cancellation.
CANCEL_CONFIRMATIONS = {"да", "подтверждаю", "отменяй", "подтверждаю отмену"}


@dataclass(frozen=True, slots=True)
class AliceAction:
    action: str
    reply: AliceReply
    transcript: str | None = None


_GREETING = "Здравствуйте! Я навык «Моя затея». Продиктуйте мысль одним сообщением или скажите «Начни запись»."
_HELP = ("Продиктуйте мысль — я сохраню её в вики. Скажите «Начни запись», чтобы диктовать "
         "несколько фраз, «Закончи запись» — чтобы завершить. «Готово?» — статус обработки. "
         "«Проверка связи» — проверка без сохранения.")
_PING = "Связь есть, заметку не создавала."
_STATUS_EMPTY = "Сейчас ничего не обрабатывается. Продиктуйте новую мысль."
_STATUS_PENDING = "Обрабатываю. Скажите «Готово?» через минуту."
_CANCEL_ASK = "Отменить текущий черновик? Скажите «да» для подтверждения."
_CANCELLED = "Черновик отменён."
_CANCEL_DECLINED = "Продолжаем запись."
_DRAFT_STARTED = "Запись началась. Диктуйте, я буду добавлять фразы."
_DRAFT_RESUMED = "Продолжаем запись. Диктуйте дальше."
_FRAGMENT_ACCEPTED = "Приняла. Продолжайте."
_NOTHING_TO_FINISH = "Запись не начиналась."
_FINISHED = ("Запись закончена, мысль в обработке. Спросите «Готово?», чтобы узнать результат.")
_EXITED = "До встречи! Черновик и принятые задания сохранены."


def _normalized(utterance: str) -> str:
    return " ".join(utterance.lower().strip().rstrip(".!").replace(",", "").split())


def route_utterance(envelope: dict, *, store, owner: str) -> AliceAction:
    """Deterministic routing; ``store`` answers status/cancel questions."""
    request = envelope.get("request") or {}
    utterance = request.get("original_utterance") or ""
    if not isinstance(utterance, str):
        utterance = ""
    normalized = _normalized(utterance)
    draft = store.draft_state(owner)
    draft_open = draft is not None and draft.get("status") == "open"

    if draft_open and draft.get("cancel_pending"):
        if normalized in CANCEL_CONFIRMATIONS:
            return AliceAction(ACTION_CONFIRM_CANCEL, render_reply(_CANCELLED))
        if normalized in {"нет", "не надо", "продолжай", "продолжить"}:
            return AliceAction(ACTION_DECLINE_CANCEL, render_reply(_CANCEL_DECLINED))

    # An open draft collects every utterance as content except explicit
    # finish/cancel/exit controls. Questions such as «Готово?» are content.
    if draft_open:
        if normalized in {"закончи запись", "запись окончена"}:
            return AliceAction(ACTION_FINISH_DRAFT, render_reply(_FINISHED))
        if normalized in {"отмени черновик", "отмена", "отмени"}:
            return AliceAction(ACTION_CANCEL_REQUEST, render_reply(_CANCEL_ASK))
        if normalized in {"выйти", "до свидания", "хватит"}:
            return AliceAction("exit", render_reply(_EXITED, end_session=True))
        if normalized in {"начни запись", "продолжи запись"}:
            return AliceAction(ACTION_RESUME_DRAFT, render_reply(_DRAFT_RESUMED))
        if normalized.startswith(VERBATIM_PREFIX):
            remainder = utterance.strip()[len(VERBATIM_PREFIX):].strip()
            return AliceAction(ACTION_APPEND_DRAFT, render_reply(_FRAGMENT_ACCEPTED), remainder)
        return AliceAction(ACTION_APPEND_DRAFT, render_reply(_FRAGMENT_ACCEPTED), utterance)

    # Whole-utterance service commands only; «готово» inside a thought
    # never triggers here because content phrases don't match exactly.
    command = COMMANDS.get(normalized)
    if command is not None:
        return _service_action(command, store=store, owner=owner)

    if normalized in ("отмена", "отмени"):
        if getattr(store, "has_pending_cancel", lambda _owner: False)(owner):
            return AliceAction("cancel_draft", render_reply(_CANCELLED))
        return AliceAction(ACTION_NOOP, render_reply("Нет активного черновика."))

    if normalized.startswith(VERBATIM_PREFIX):
        verbatim = utterance.strip()[len(VERBATIM_PREFIX):].strip()
        if verbatim:
            return AliceAction(ACTION_VERBATIM, render_reply("Приняла мысль в обработку."), verbatim)
        return AliceAction("empty_verbatim", render_reply("Скажите текст после «Запиши дословно»."))

    greeting_phrases = (
        "", "запуск навыка моя затея", "моя затея",
        "алиса запусти навык моя затея", "запусти навык моя затея",
    )
    if normalized in greeting_phrases:
        return AliceAction("greeting", render_reply(_GREETING))

    if normalized in ("выйти", "до свидания", "хватит"):
        return AliceAction("exit", render_reply(_EXITED, end_session=True))

    # Any other utterance becomes content (plan: мысли записываются как содержание).
    return AliceAction(ACTION_NEW_IDEA, render_reply(
        "Приняла мысль в обработку. Спросите «Готово?», чтобы узнать результат."))


def _service_action(command: str, *, store, owner: str) -> AliceAction:
    if command == ACTION_HELP:
        return AliceAction(ACTION_HELP, render_reply(_HELP, end_session=True))
    if command == ACTION_PING:
        return AliceAction(ACTION_PING, render_reply(_PING, end_session=True))
    if command == ACTION_STATUS:
        return AliceAction(ACTION_STATUS, _status_reply(store, owner))
    if command == ACTION_NEXT_REPLY:
        return AliceAction(ACTION_NEXT_REPLY, render_reply("Продолжаю."))
    if command == ACTION_START_DRAFT:
        return AliceAction(ACTION_START_DRAFT, render_reply(_DRAFT_STARTED))
    if command == ACTION_FINISH_DRAFT:
        return AliceAction(ACTION_FINISH_DRAFT, render_reply(_FINISHED))
    if command == ACTION_CANCEL_DRAFT:
        return AliceAction(ACTION_CANCEL_DRAFT, render_reply(_CANCELLED))
    return AliceAction(ACTION_NEW_IDEA, render_reply("Приняла мысль в обработку."))


def _status_reply(store, owner: str) -> AliceReply:
    pending = store.pending_count(owner)
    if pending > 0:
        return render_reply(_STATUS_PENDING)
    latest = store.latest_reply(owner)
    if latest is None:
        return render_reply(_STATUS_EMPTY)
    if latest["status"] == "done":
        from backend.src.voice_gateway.alice.render import chunk_text
        pages = chunk_text(latest["reply"] or "Готово.")
        page_index, total = store.reply_page(owner) if hasattr(store, "reply_page") else (0, len(pages))
        text = pages[page_index]
        if page_index + 1 < total:
            text += "\n(Скажите «Дальше», чтобы продолжить.)"
        return render_reply(text)
    if latest["status"] == "needs_review":
        return render_reply("Запись сохранила, но обновление заметок требует проверки.")
    return render_reply("Не получилось обработать последнюю мысль. Повторите её, пожалуйста.")


__all__ = ["route_utterance", "AliceAction", "COMMANDS", "VERBATIM_PREFIX"]
