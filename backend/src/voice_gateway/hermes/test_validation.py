"""Tests for structured Hermes response validation (ТЗ sections 22, 24)."""
import json

import pytest

from backend.src.voice_gateway.hermes.validation import (
    HermesValidationError,
    parse_hermes_response,
)


def test_valid_minimal_reply_only():
    raw = json.dumps({"reply": "Привет!"})
    result = parse_hermes_response(raw)
    assert result.reply == "Привет!"
    assert result.note.create is False
    assert result.note.title == ""
    assert result.note.content == ""
    assert result.note.tags == []


def test_valid_full_note():
    raw = json.dumps(
        {
            "reply": "Записал.",
            "note": {
                "create": True,
                "title": "Покупки",
                "content": "- USB-C кабель\n- батарея",
                "tags": ["voice", "idea"],
            },
        }
    )
    result = parse_hermes_response(raw)
    assert result.note.create is True
    assert result.note.title == "Покупки"
    assert result.note.tags == ["voice", "idea"]


def test_missing_reply_is_invalid():
    with pytest.raises(HermesValidationError) as exc_info:
        parse_hermes_response(json.dumps({"note": {"create": False}}))
    # raw payload is preserved for archiving
    assert exc_info.value.raw.startswith('{"note"')


def test_plain_text_response_is_invalid():
    with pytest.raises(HermesValidationError):
        parse_hermes_response("Просто текстовый ответ без JSON.")


def test_empty_string_is_invalid():
    with pytest.raises(HermesValidationError):
        parse_hermes_response("")


def test_json_fence_is_repaired():
    raw = '```json\n{"reply": "OK"}\n```'
    assert parse_hermes_response(raw).reply == "OK"


def test_json_block_markers_are_repaired():
    raw = 'Понял. <json>\n{"reply": "Готово."}\n</json>'
    assert parse_hermes_response(raw).reply == "Готово."


def test_trailing_comma_is_repaired():
    raw = '{"reply": "OK", "note": {"create": false, "tags": [],},}'
    assert parse_hermes_response(raw).reply == "OK"


def test_unrepairable_garbage_keeps_original_raw():
    garbage = '```json\n{"reply": "OK"\n```'
    with pytest.raises(HermesValidationError) as exc_info:
        parse_hermes_response(garbage)
    assert exc_info.value.raw == garbage


def test_invalid_schema_is_invalid_even_with_valid_json():
    raw = json.dumps({"answer": "reply is wrong field"})
    with pytest.raises(HermesValidationError):
        parse_hermes_response(raw)


def test_cyrillic_roundtrip():
    raw = json.dumps(
        {"reply": "Записал: купить USB-C кабель для лаборатории."},
        ensure_ascii=False,
    )
    assert parse_hermes_response(raw).reply == (
        "Записал: купить USB-C кабель для лаборатории."
    )


def test_syntax_diagnostics_have_location_without_response_text():
    with pytest.raises(HermesValidationError) as caught:
        parse_hermes_response('{"reply":')
    assert caught.value.safe_diagnostics == (
        {"type": "json_syntax", "line": 1, "column": 10},
    )
    assert caught.value.raw == '{"reply":'
    assert caught.value.detail == str(caught.value)


def test_schema_diagnostics_keep_fixed_paths_and_hide_extra_names_and_values():
    raw = json.dumps({"reply": "private reply", "note": {"knowledge": {
        "operation": "capture", "pages": [{"path": "https://private-url.example",
        "title": 123, "content": {"secret": "private content"}, "sources": []}],
        "private-token-as-field-name": "private token value",
        # Even a known schema name is hidden when it is an unknown extra here.
        "reply": "another private value",
    }}})
    with pytest.raises(HermesValidationError) as caught:
        parse_hermes_response(raw)
    diagnostics = caught.value.safe_diagnostics
    assert {"type": "string_type", "path": ["note", "knowledge", "pages", 0, "content"]} in diagnostics
    assert {"type": "extra_forbidden", "path": ["note", "knowledge", "<extra>"]} in diagnostics
    assert {"type": "extra_forbidden", "path": ["note", "knowledge", "reply"]} not in diagnostics
    assert "private" not in json.dumps(diagnostics)
    assert caught.value.raw == raw
    assert isinstance(caught.value.detail, str)


def test_safe_diagnostics_bound_count_depth_and_untrusted_error_metadata():
    from backend.src.voice_gateway.hermes.validation import _safe_schema_errors
    errors = [{"type": "private-error-name", "loc": ("private-field-name",)}]
    errors += [{"type": "string_type", "loc": ("note",) * 30 + ("private-tail",),
                "input": "private input", "msg": "private message", "ctx": {"private": "context"}}] * 30
    diagnostics = _safe_schema_errors(errors)
    assert len(diagnostics) == 8
    assert diagnostics[0] == {"type": "schema_error", "path": ["<field>"]}
    assert len(diagnostics[1]["path"]) == 8
    assert diagnostics[1]["path"][-1] == "<truncated>"
    assert "private" not in json.dumps(diagnostics)
    assert _safe_schema_errors([{"type": "string_type", "loc": ("pages", 10**100)}]) == (
        {"type": "string_type", "path": ["pages", "<index>"]},
    )
