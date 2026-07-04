"""
tests/conftest.py
-------------------
Shared pytest fixtures used across the test suite.
"""
import pytest


@pytest.fixture(autouse=True)
def no_real_llm_sleep(monkeypatch):
    """LLMClient.generate()'s exponential-backoff retries would otherwise
    add several real seconds to every retry/failure test in the suite.
    Applied automatically to every test via autouse."""
    monkeypatch.setattr("app.llm_client.time.sleep", lambda seconds: None)
