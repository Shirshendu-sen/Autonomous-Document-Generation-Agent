"""
tests/test_config.py
---------------------
Covers Step 2: configuration is loaded correctly from environment
variables, with sane defaults when nothing is set.
"""
import importlib


def test_defaults_when_no_env_vars_set(monkeypatch):
    for var in ["LLM_PROVIDER", "GROQ_API_KEY", "GROQ_MODEL", "OLLAMA_HOST",
                "OLLAMA_MODEL", "MAX_REFLECTION_ROUNDS", "LLM_MAX_RETRIES",
                "REQUEST_TIMEOUT_SECONDS"]:
        monkeypatch.delenv(var, raising=False)

    from app import config
    importlib.reload(config)

    assert config.LLM_PROVIDER == "mock"
    assert config.GROQ_MODEL == "llama-3.3-70b-versatile"
    assert config.OLLAMA_HOST == "http://localhost:11434"
    assert config.OLLAMA_MODEL == "llama3"
    assert config.MAX_REFLECTION_ROUNDS == 2
    assert config.LLM_MAX_RETRIES == 2
    assert config.REQUEST_TIMEOUT_SECONDS == 30
    assert config.MIN_REQUEST_LENGTH == 8
    assert config.MAX_REQUEST_LENGTH == 4000


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "GROQ")
    monkeypatch.setenv("MAX_REFLECTION_ROUNDS", "5")

    from app import config
    importlib.reload(config)

    assert config.LLM_PROVIDER == "groq"  # lower-cased
    assert config.MAX_REFLECTION_ROUNDS == 5

    # leave the module in its default state for any tests that follow
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("MAX_REFLECTION_ROUNDS", raising=False)
    importlib.reload(config)


def test_output_dir_is_created():
    from app import config
    assert config.OUTPUT_DIR.exists()
    assert config.OUTPUT_DIR.is_dir()
