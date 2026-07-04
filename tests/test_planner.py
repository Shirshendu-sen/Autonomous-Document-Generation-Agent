"""
tests/test_planner.py
----------------------
Covers Step 6: the autonomous planner, including its three-tier resilience
against LLM output that isn't clean JSON (direct parse -> self-correction
repair call -> deterministic template fallback). Uses fake LLMClient
stand-ins rather than the real Mock/Groq/Ollama backends, so each parsing
path can be exercised in isolation.
"""
import json

import pytest

from app.llm_client import LLMClient, LLMError, MockLLM
from app.planner import create_plan, _strip_code_fences, _try_parse_plan
from app.templates import DOCUMENT_TYPES


class _ScriptedClient(LLMClient):
    """Returns each string in ``responses`` in order, one per call."""

    name = "scripted"

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def _call(self, system, user, json_mode):
        self.calls += 1
        return self._responses.pop(0)


class _AlwaysRaisesClient(LLMClient):
    name = "always-raises"

    def _call(self, system, user, json_mode):
        raise ConnectionError("provider unreachable")


VALID_PLAN = {
    "document_type": "project_plan",
    "title": "Mobile App Launch",
    "audience": "Leadership",
    "assumptions": ["No budget was given."],
    "sections": [
        {"id": "overview", "title": "Overview", "goal": "Summarise.", "table_columns": None},
    ],
}


# ---- happy path (real Mock backend) -------------------------------------------

def test_create_plan_with_mock_llm_produces_valid_plan():
    plan = create_plan("Write meeting minutes for our weekly product sync.", MockLLM())
    assert plan.document_type == "meeting_minutes"
    assert len(plan.sections) > 0
    assert isinstance(plan.assumptions, list)


# ---- JSON parsing helpers ------------------------------------------------------

def test_strip_code_fences_removes_json_fence():
    wrapped = "```json\n" + json.dumps(VALID_PLAN) + "\n```"
    assert json.loads(_strip_code_fences(wrapped)) == VALID_PLAN


def test_strip_code_fences_removes_plain_fence():
    wrapped = "```\n" + json.dumps(VALID_PLAN) + "\n```"
    assert json.loads(_strip_code_fences(wrapped)) == VALID_PLAN


def test_try_parse_plan_returns_none_for_missing_keys():
    assert _try_parse_plan(json.dumps({"title": "no sections here"})) is None


def test_try_parse_plan_returns_none_for_invalid_json():
    assert _try_parse_plan("not json at all") is None


# ---- three-tier resilience -----------------------------------------------------

def test_create_plan_parses_first_reply_directly():
    client = _ScriptedClient([json.dumps(VALID_PLAN)])
    plan = create_plan("some request", client)
    assert plan.title == "Mobile App Launch"
    assert client.calls == 1  # no repair call needed


def test_create_plan_uses_repair_call_when_first_reply_is_malformed():
    client = _ScriptedClient(["this is not json", json.dumps(VALID_PLAN)])
    plan = create_plan("some request", client)
    assert plan.title == "Mobile App Launch"
    assert client.calls == 2  # first attempt + one repair attempt


def test_create_plan_falls_back_to_template_when_both_replies_are_malformed():
    client = _ScriptedClient(["garbage one", "garbage two"])
    plan = create_plan("Create a proposal for a new vendor contract.", client)
    assert plan.document_type in DOCUMENT_TYPES
    assert "fallback planner" in plan.assumptions[0]
    assert len(plan.sections) > 0


def test_create_plan_falls_back_to_template_when_repair_call_raises(monkeypatch):
    client = _ScriptedClient(["garbage one"])

    # After the first (malformed) reply, simulate the repair call itself
    # failing at the network level (raises LLMError after its own retries).
    original_generate = client.generate

    def _generate_then_raise(system, user, json_mode=False):
        if client.calls == 0:
            return original_generate(system, user, json_mode)
        raise LLMError("repair call unreachable")

    monkeypatch.setattr(client, "generate", _generate_then_raise)
    plan = create_plan("Create a proposal for a new vendor contract.", client)
    assert plan.document_type in DOCUMENT_TYPES


def test_create_plan_backfills_missing_optional_keys():
    minimal = {
        "document_type": "project_plan",
        "title": "Minimal Plan",
        "sections": [{"id": "overview", "title": "Overview", "goal": "Summarise."}],
    }
    client = _ScriptedClient([json.dumps(minimal)])
    plan = create_plan("some request", client)
    assert plan.audience is None
    assert plan.assumptions == []
    assert plan.sections[0].table_columns is None


def test_create_plan_propagates_llm_error_when_initial_call_fails():
    with pytest.raises(LLMError):
        create_plan("some request", _AlwaysRaisesClient())


def test_create_plan_falls_back_to_template_when_json_is_valid_but_fails_plan_validation():
    # Parses as JSON and passes the "sections"/"document_type" shape sniff,
    # but a section is missing required fields ("title", "goal") -- Plan(**parsed)
    # should fail Pydantic validation, not crash create_plan.
    schema_invalid = {
        "document_type": "project_plan",
        "title": "Broken Plan",
        "sections": [{"id": "overview"}],
    }
    client = _ScriptedClient([json.dumps(schema_invalid)])
    plan = create_plan("Create a proposal for a new vendor contract.", client)
    assert plan.document_type in DOCUMENT_TYPES
    assert "fallback planner" in plan.assumptions[0]
