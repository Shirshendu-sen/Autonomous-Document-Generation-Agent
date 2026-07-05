"""
tests/test_llm_client.py
-------------------------
Covers Step 5: the provider-agnostic LLM interface -- retry/backoff
behaviour, the Mock backend's canned responses, and the get_llm_client()
factory's fallback-to-Mock behaviour when a configured provider is
unavailable. No real network calls are made.
"""
import json

import pytest

from app import config
from app.llm_client import (
    LLMClient,
    LLMError,
    MockLLM,
    GroqLLM,
    OllamaLLM,
    get_llm_client,
)
from app.planner import PLANNER_SYSTEM_PROMPT
from app.executor import SECTION_SYSTEM_PROMPT


# ---- retry / backoff behaviour ------------------------------------------------

class _FlakyClient(LLMClient):
    """Fails twice, then succeeds on the third attempt."""

    name = "flaky"

    def __init__(self):
        self.calls = 0

    def _call(self, system, user, json_mode):
        self.calls += 1
        if self.calls < 3:
            raise ConnectionError("simulated transient failure")
        return "ok"


class _AlwaysFailsClient(LLMClient):
    name = "always-fails"

    def __init__(self):
        self.calls = 0

    def _call(self, system, user, json_mode):
        self.calls += 1
        raise TimeoutError("simulated permanent failure")


# Backoff sleeps are patched out for every test via the autouse
# no_real_llm_sleep fixture in tests/conftest.py.


def test_generate_retries_and_recovers_from_transient_failures():
    client = _FlakyClient()
    result = client.generate("system", "user")
    assert result == "ok"
    assert client.calls == 3  # 1 initial attempt + 2 retries (default LLM_MAX_RETRIES=2)


def test_generate_raises_llm_error_after_exhausting_retries():
    client = _AlwaysFailsClient()
    with pytest.raises(LLMError):
        client.generate("system", "user")
    assert client.calls == config.LLM_MAX_RETRIES + 1


# ---- Retry-After-aware backoff on 429s -----------------------------------------

class _FakeResponse:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}


def test_retry_after_seconds_honours_header_on_429():
    import requests
    err = requests.exceptions.HTTPError("429")
    err.response = _FakeResponse(429, {"retry-after": "5"})
    wait = LLMClient._retry_after_seconds(err)
    assert wait is not None and 5 <= wait <= 6  # + up to 1s jitter


def test_retry_after_seconds_caps_extreme_header_value():
    import requests
    err = requests.exceptions.HTTPError("429")
    err.response = _FakeResponse(429, {"retry-after": "9999"})
    wait = LLMClient._retry_after_seconds(err)
    assert wait is not None and wait <= 31  # capped at 30s + jitter


def test_retry_after_seconds_returns_none_without_header_or_for_non_429():
    import requests
    no_header_err = requests.exceptions.HTTPError("429")
    no_header_err.response = _FakeResponse(429, {})
    assert LLMClient._retry_after_seconds(no_header_err) is None

    assert LLMClient._retry_after_seconds(ConnectionError("boom")) is None


def test_generate_sleeps_for_retry_after_duration_on_429(monkeypatch):
    import requests

    class _RateLimitedThenOkClient(LLMClient):
        name = "rate-limited"

        def __init__(self):
            self.calls = 0

        def _call(self, system, user, json_mode):
            self.calls += 1
            if self.calls == 1:
                err = requests.exceptions.HTTPError("429")
                err.response = _FakeResponse(429, {"retry-after": "3"})
                raise err
            return "ok"

    slept = []
    monkeypatch.setattr("app.llm_client.time.sleep", lambda seconds: slept.append(seconds))

    client = _RateLimitedThenOkClient()
    result = client.generate("system", "user")
    assert result == "ok"
    assert len(slept) == 1
    assert 3 <= slept[0] <= 4  # honoured the server's Retry-After, not the exponential guess


# ---- Groq / Ollama construction (no network calls made) ----------------------

def test_groq_llm_requires_api_key():
    with pytest.raises(LLMError):
        GroqLLM(api_key="", model="llama-3.3-70b-versatile")


def test_ollama_llm_strips_trailing_slash_from_host():
    client = OllamaLLM(host="http://localhost:11434/", model="llama3")
    assert client.host == "http://localhost:11434"


# ---- get_llm_client() factory fallback behaviour ------------------------------

def test_factory_returns_mock_when_provider_is_mock(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "mock")
    client = get_llm_client()
    assert isinstance(client, MockLLM)


def test_factory_falls_back_to_mock_when_groq_key_missing(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "groq")
    monkeypatch.setattr(config, "GROQ_API_KEY", "")
    client = get_llm_client()
    assert isinstance(client, MockLLM)


def test_factory_falls_back_to_mock_when_ollama_unreachable(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "ollama")
    monkeypatch.setattr(config, "OLLAMA_HOST", "http://localhost:1")  # nothing listens here

    def _raise(*args, **kwargs):
        raise ConnectionError("no server")

    monkeypatch.setattr("app.llm_client.OllamaLLM._call", _raise)
    client = get_llm_client()
    assert isinstance(client, MockLLM)


def test_factory_falls_back_to_mock_for_unknown_provider(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "not-a-real-provider")
    client = get_llm_client()
    assert isinstance(client, MockLLM)


# ---- MockLLM canned-response behaviour ----------------------------------------

def test_mock_llm_returns_valid_plan_json():
    client = MockLLM()
    raw = client.generate(PLANNER_SYSTEM_PROMPT, "Create a project plan for our Q3 launch.")
    data = json.loads(raw)
    assert data["document_type"] == "project_plan"
    assert len(data["sections"]) > 0


def test_mock_llm_returns_short_first_draft_for_prose_section():
    client = MockLLM()
    prompt = (
        "DOCUMENT TITLE: X\nSECTION TITLE: Overview\nSECTION GOAL: summarise the project\n"
        "TABLE COLUMNS: None\n"
    )
    raw = client.generate(SECTION_SYSTEM_PROMPT, prompt)
    assert "Overview" in raw
    assert "(revised)" not in raw


def test_mock_llm_returns_revised_prose_when_flagged():
    client = MockLLM()
    prompt = (
        "DOCUMENT TITLE: X\nSECTION TITLE: Overview\nSECTION GOAL: summarise the project\n"
        "TABLE COLUMNS: None\nPREVIOUS DRAFT WAS FLAGGED BY QUALITY REVIEW: too short\n"
    )
    raw = client.generate(SECTION_SYSTEM_PROMPT, prompt)
    assert "(revised)" in raw


def test_mock_llm_returns_json_rows_for_table_section():
    client = MockLLM()
    prompt = (
        "DOCUMENT TITLE: X\nSECTION TITLE: Risks\nSECTION GOAL: list risks\n"
        "TABLE COLUMNS: ['Risk', 'Impact', 'Mitigation']\n"
    )
    raw = client.generate(SECTION_SYSTEM_PROMPT, prompt)
    rows = json.loads(raw)
    assert isinstance(rows, list) and len(rows) == 3
    assert set(rows[0].keys()) == {"Risk", "Impact", "Mitigation"}


def test_mock_llm_returns_reflection_style_json():
    # reflection.py doesn't exist yet (a later step) -- this exercises the
    # MockLLM branch that will back it, using a system prompt shaped the
    # way that future module's REFLECTION_SYSTEM_PROMPT is.
    client = MockLLM()
    system = "You are the quality-reviewer module of an autonomous document-generation agent."
    user = (
        "ORIGINAL REQUEST:\nWrite meeting minutes.\n\n"
        "---SECTION---\nID: overview\nTITLE: Overview\nCONTENT:\nToo short.\n"
    )
    raw = client.generate(system, user)
    data = json.loads(raw)
    assert data["overall_ok"] is False
    assert data["feedback"][0]["id"] == "overview"
    assert data["feedback"][0]["ok"] is False
