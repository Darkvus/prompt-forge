import pytest

from app.generator import select_entries
from app.llm import Llm, LLMError, parse_json_object, price_for
from app.toolkit import Entry


def test_parse_json_with_fences():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_invalid():
    with pytest.raises(LLMError):
        parse_json_object("no json here")


def test_price_lookup_dated_and_unknown():
    assert price_for("openai", "gpt-5.4-2026-01-01") == price_for("openai", "gpt-5.4")
    assert price_for("gemini", "gemini-9") is None


def test_select_filters_invented_names(monkeypatch):
    llm = Llm("openai", "m", "k")
    monkeypatch.setattr(Llm, "complete", lambda self, *a, **k: '{"entries": ["real", "fake", "real"], '
                                                              '"stack_summary": "s", "reasoning": "r"}')
    sel = select_entries(llm, "def", {"real": Entry("skill", "real", "d", "b")})
    assert sel.entries == ["real"]


def test_key_not_in_repr():
    assert "secret" not in repr(Llm("openai", "m", "secret"))
