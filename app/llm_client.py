"""
app/llm_client.py
------------------
A tiny provider-agnostic LLM interface.

Every other module (planner, executor, reflection) only ever calls
``llm.generate(system, user, json_mode)`` -- swapping providers (Groq <-> Ollama
<-> Mock) is a one-line environment-variable change, not a code change
scattered across files.
"""
from __future__ import annotations

import json
import logging
import random
import time
from abc import ABC, abstractmethod
from typing import List, Optional

import requests

from app import config

logger = logging.getLogger("agent.llm")

_HEALTH_CHECK_SYSTEM = "You are a health check."
_HEALTH_CHECK_USER = "Reply with OK."


class LLMError(Exception):
    """Raised when a provider fails after all retries have been exhausted."""


class LLMClient(ABC):
    """Common interface every LLM backend implements."""

    name: str = "base"

    @abstractmethod
    def _call(self, system: str, user: str, json_mode: bool) -> str:
        """Provider-specific implementation. Should raise on any failure
        (network error, timeout, non-2xx response, malformed payload) so the
        retry wrapper in ``generate`` can catch it uniformly."""

    def generate(self, system: str, user: str, json_mode: bool = False) -> str:
        """Public entry point used by planner/executor/reflection.

        Wraps ``_call`` with exponential-backoff retries, since free-tier
        hosted models and local models both occasionally time out or
        rate-limit. Raises ``LLMError`` only after every attempt has failed.
        """
        last_err: Optional[Exception] = None
        for attempt in range(1, config.LLM_MAX_RETRIES + 2):  # e.g. 1 try + 2 retries
            try:
                return self._call(system, user, json_mode)
            except Exception as e:
                last_err = e
                # Exponential backoff with jitter, capped at 8s, so retries
                # don't hammer a struggling provider in lock-step.
                wait = min(2 ** attempt + random.random(), 8)
                logger.warning("[%s] generate() attempt %d failed: %s -- retrying in %.1fs",
                                self.name, attempt, e, wait)
                time.sleep(wait)
        raise LLMError(f"{self.name} failed after retries: {last_err}")


# ---- Groq -- free-tier hosted inference, OpenAI-compatible REST API --------
class GroqLLM(LLMClient):
    """Primary provider. Groq exposes a plain OpenAI-compatible chat
    completions endpoint, so a raw `requests.post` is enough -- no SDK
    dependency needed."""

    name = "groq"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set")
        self.api_key = api_key
        self.model = model
        self.url = "https://api.groq.com/openai/v1/chat/completions"

    def _call(self, system: str, user: str, json_mode: bool) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.4,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        resp = requests.post(
            self.url,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=config.REQUEST_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ---- Ollama -- fully local, free, runs on the developer's machine ----------
class OllamaLLM(LLMClient):
    """Optional local provider. Talks to a locally running Ollama server via
    its REST API -- no internet access or API key required."""

    name = "ollama"

    def __init__(self, host: str, model: str):
        self.host = host.rstrip("/")
        self.model = model

    def _call(self, system: str, user: str, json_mode: bool) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        resp = requests.post(f"{self.host}/api/chat", json=payload, timeout=config.REQUEST_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]


# ---- Mock -- deterministic, offline, zero-dependency stand-in -------------
# Satisfies the same contract as a real LLM so the whole pipeline is runnable
# and testable with no API key, no internet, and no local model. It also
# deliberately under-writes the first draft of prose sections so the
# reflection/auto-revision loop (added in a later step) has something real
# to fix live.
class MockLLM(LLMClient):
    name = "mock"

    def _call(self, system: str, user: str, json_mode: bool) -> str:
        if "Return ONLY a JSON object describing the document plan" in system:
            return self._mock_plan(user)
        if "You are drafting the content for ONE section" in system:
            return self._mock_section(system, user)
        if "quality-reviewer" in system:
            return self._mock_reflection(user)
        return "Mock response."

    def _mock_plan(self, user: str) -> str:
        from app.templates import classify_keyword_fallback, TEMPLATES

        doc_type = classify_keyword_fallback(user)
        title = self._guess_title(user, doc_type)
        assumptions = self._guess_assumptions(user)
        sections = [
            {"id": sid, "title": stitle, "goal": f"Explain {stitle.lower()} relevant to: {title}",
             "table_columns": cols}
            for sid, stitle, cols in TEMPLATES[doc_type]
        ]
        plan = {
            "document_type": doc_type, "title": title, "audience": "Internal stakeholders",
            "assumptions": assumptions, "sections": sections,
        }
        return json.dumps(plan)

    _FILLER_PREFIXES = [
        "we need some kind of document for", "we need a document for", "we need",
        "can you create", "can you write", "can you draft", "can you generate",
        "please create", "please write", "please draft", "please generate",
        "help me create", "help me write", "help me draft",
        "create a", "create", "write a", "write", "draft a", "draft",
        "generate a", "generate", "build a", "build",
    ]

    @classmethod
    def _guess_title(cls, user: str, doc_type: str) -> str:
        text = user.strip()
        first_clause = text.split(". ")[0].split(", but")[0].split(" but ")[0]
        lowered = first_clause.lower()
        for prefix in cls._FILLER_PREFIXES:
            if lowered.startswith(prefix):
                first_clause = first_clause[len(prefix):].strip()
                lowered = first_clause.lower()
                break
        words = [w for w in first_clause.split() if any(c.isalpha() for c in w)]
        snippet = " ".join(words[:9]).title() if words else "Untitled Document"
        label = "SOP" if doc_type == "sop" else doc_type.replace("_", " ").title()
        return f"{label}: {snippet}" if snippet.lower() not in label.lower() else label

    @staticmethod
    def _guess_assumptions(user: str) -> List[str]:
        text = user.lower()
        assumptions = []
        if "budget" not in text and "cost" not in text and "$" not in text:
            assumptions.append("No budget was specified, so illustrative placeholder figures are used.")
        if "deadline" not in text and "by " not in text and "date" not in text:
            assumptions.append("No firm deadline was given, so a standard timeline was assumed.")
        if "team" not in text and "stakeholder" not in text and "audience" not in text:
            assumptions.append("No specific audience was named, so content is written for general internal stakeholders.")
        if not assumptions:
            assumptions.append("Request was specific enough that no major assumptions were required.")
        return assumptions

    def _mock_section(self, system: str, user: str) -> str:
        is_revision = "PREVIOUS DRAFT WAS FLAGGED" in user
        title = self._extract(user, "SECTION TITLE:")
        goal = self._extract(user, "SECTION GOAL:")
        columns_raw = self._extract(user, "TABLE COLUMNS:")

        if columns_raw and columns_raw != "None":
            cols = [c.strip() for c in columns_raw.strip("[]").replace("'", "").split(",")]
            rows = [{c: f"{c} {i}" for c in cols} for i in range(1, 4)]
            return json.dumps(rows)

        if is_revision:
            return (
                f"{title} (revised): Based on the request, this section addresses {goal.lower()}. "
                f"Specifically, it covers the current situation, the concrete steps being proposed, "
                f"who is responsible, and how success will be measured. Placeholder figures and dates "
                f"are used where the original request did not specify them, and these are flagged in the "
                f"Assumptions section of this document. This expanded draft was produced automatically "
                f"after the agent's self-check flagged the first draft as too brief, and now contains "
                f"sufficient detail for a business reader to act on without needing to ask follow-up "
                f"questions. Next, the relevant owners should review this section and confirm the "
                f"assumptions before the document is finalised and circulated."
            )

        # Deliberately short first draft so a later reflection pass has
        # something real to catch.
        return (
            f"{title}: this section addresses {goal.lower()}. "
            f"A draft summary is provided based on the request, with placeholder specifics used where "
            f"the original request did not include them. Further detail can be added once more "
            f"information is available from stakeholders."
        )

    @staticmethod
    def _extract(text: str, marker: str) -> str:
        if marker not in text:
            return ""
        after = text.split(marker, 1)[1]
        return after.split("\n", 1)[0].strip()

    def _mock_reflection(self, user: str) -> str:
        feedback = []
        overall_ok = True
        blocks = user.split("---SECTION---")[1:]
        for block in blocks:
            sid = self._extract(block, "ID:")
            content = block.split("CONTENT:", 1)[1].strip() if "CONTENT:" in block else ""
            is_table = content.strip().startswith("[")
            word_count = len(content.split())
            if not is_table and word_count < 60:
                feedback.append({"id": sid, "ok": False, "issue": "Section is too brief and lacks concrete detail."})
                overall_ok = False
            else:
                feedback.append({"id": sid, "ok": True, "issue": None})
        return json.dumps({"overall_ok": overall_ok, "feedback": feedback})


def get_llm_client() -> LLMClient:
    """Builds the client configured via ``LLM_PROVIDER``.

    Falls back to ``MockLLM`` if the configured provider is unreachable
    (missing key, network error, local server not running) or unrecognised,
    so the API never becomes totally unusable because of an environment
    misconfiguration.
    """
    provider = config.LLM_PROVIDER
    try:
        if provider == "groq":
            client = GroqLLM(config.GROQ_API_KEY, config.GROQ_MODEL)
            client._call(_HEALTH_CHECK_SYSTEM, _HEALTH_CHECK_USER, json_mode=False)
            return client
        if provider == "ollama":
            client = OllamaLLM(config.OLLAMA_HOST, config.OLLAMA_MODEL)
            client._call(_HEALTH_CHECK_SYSTEM, _HEALTH_CHECK_USER, json_mode=False)
            return client
    except Exception as e:
        logger.warning("Configured provider '%s' unavailable (%s) -- falling back to MockLLM.", provider, e)
    if provider not in ("groq", "ollama", "mock"):
        logger.warning("Unknown LLM_PROVIDER '%s' -- falling back to MockLLM.", provider)
    return MockLLM()
