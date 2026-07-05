"""
tests/conftest.py
-------------------
Shared pytest fixtures used across the test suite.
"""
import dotenv

# The suite is designed to run hermetically against LLMClient fakes/mocks
# (MockLLM, plus hand-written stubs for retry/failure scenarios) -- never a
# live provider. app/config.py calls dotenv.load_dotenv() at *import* time,
# which would otherwise pull a developer's real local `.env` (e.g.
# LLM_PROVIDER=groq + a real GROQ_API_KEY) into every test run -- making the
# required-test-case tests hit the live Groq API instead of MockLLM (flaky,
# rate-limited, burns real quota) and breaking test_config.py's "defaults
# when no env vars are set" case. Neutralise it before app.config (or
# anything importing it) is loaded for the first time -- module-level code
# here runs before pytest collects/imports any test_*.py file.
dotenv.load_dotenv = lambda *args, **kwargs: None

import pytest


@pytest.fixture(autouse=True)
def no_real_llm_sleep(monkeypatch):
    """LLMClient.generate()'s exponential-backoff retries would otherwise
    add several real seconds to every retry/failure test in the suite.
    Applied automatically to every test via autouse."""
    monkeypatch.setattr("app.llm_client.time.sleep", lambda seconds: None)
