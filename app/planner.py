"""
app/planner.py
--------------
Turns a free-text user request into a structured, autonomous execution plan.

This is the core "autonomous planning & reasoning" stage: the agent -- not
the user -- decides what the document should contain and how it should be
structured, and is instructed to never ask a follow-up question. Instead it
must state an explicit assumption and proceed, which is what lets ambiguous
requests be handled in a single API call.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import ValidationError

from app.llm_client import LLMClient, LLMError
from app.schemas import Plan
from app.templates import TEMPLATES, DOCUMENT_TYPES, default_plan_dict, classify_keyword_fallback

logger = logging.getLogger("agent.planner")

PLANNER_SYSTEM_PROMPT = f"""You are the planning module of an autonomous document-generation agent.

Given a user's natural-language request, decide:
1. Which document type it is: one of {DOCUMENT_TYPES} (pick the closest match; if truly none fit, use "business_report").
2. A concise, professional title for the document.
3. The intended audience, if inferable (else null).
4. A list of ASSUMPTIONS you are making to fill any gaps, ambiguities, or missing
   information in the request (e.g. missing budget, deadline, audience, or scope).
   Never ask the user a follow-up question -- always make the most reasonable
   assumption and state it explicitly here instead.
5. An ordered list of SECTIONS the document should contain, each with:
   id (snake_case), title, goal (one sentence), table_columns (list or null
   for naturally tabular data like action items/milestones/budget/risks).

Typical section sets per document type (reference, not rigid):
{json.dumps(TEMPLATES, indent=2)}

Return ONLY a JSON object describing the document plan, with this exact shape,
and no prose, no markdown fences, no commentary:
{{
  "document_type": "...", "title": "...", "audience": "..." or null,
  "assumptions": ["...", "..."],
  "sections": [{{"id": "...", "title": "...", "goal": "...", "table_columns": ["..."] or null}}]
}}
"""


def _strip_code_fences(text: str) -> str:
    """Strips ```json ... ``` / ``` ... ``` wrappers some models add around
    JSON output despite being told not to."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    return text.strip()


def _try_parse_plan(raw: str) -> Optional[dict]:
    """Attempts to parse the model's raw output as a valid plan dict.
    Returns None (never raises) so callers can decide how to recover."""
    try:
        data = json.loads(_strip_code_fences(raw))
        if "sections" in data and "document_type" in data and isinstance(data["sections"], list):
            return data
    except (json.JSONDecodeError, TypeError, KeyError):
        pass
    return None


def _deterministic_fallback_plan(user_request: str) -> dict:
    doc_type = classify_keyword_fallback(user_request)
    title_guess = user_request.strip().split(".")[0][:80] or "Untitled Document"
    return default_plan_dict(doc_type, title_guess)


def create_plan(user_request: str, llm: LLMClient) -> Plan:
    """Produces a validated ``Plan`` for the given request.

    Four-tier resilience against free/small models that don't reliably
    return clean, schema-correct JSON:
      1. Parse the model's first reply directly.
      2. If that fails, send the exact parse error back to the model once,
         asking it to self-correct.
      3. If it *still* fails, fall back to a deterministic template plan
         (see app/templates.py).
      4. Even a reply that parses as JSON can be missing a field Plan
         requires (e.g. a section without a "title") -- if building the
         final Plan fails validation, fall back to the same deterministic
         template rather than raising, so the caller never sees a 500 just
         because the LLM's output was unreliable.
    """
    raw = llm.generate(PLANNER_SYSTEM_PROMPT, user_request, json_mode=True)
    parsed = _try_parse_plan(raw)

    if parsed is None:
        logger.warning("Planner output failed to parse as JSON; asking the LLM to correct it once.")
        repair_prompt = (
            f"Your previous reply could not be parsed as JSON. Original request:\n{user_request}\n\n"
            f"Your previous (invalid) reply was:\n{raw}\n\n"
            "Reply again with ONLY the corrected JSON object, no other text."
        )
        try:
            raw2 = llm.generate(PLANNER_SYSTEM_PROMPT, repair_prompt, json_mode=True)
            parsed = _try_parse_plan(raw2)
        except LLMError:
            # The repair call itself failed (provider unreachable after
            # retries) -- fall through to the deterministic fallback below
            # rather than propagating, since we can still produce a usable
            # plan without the LLM.
            parsed = None

    if parsed is None:
        logger.warning("Planner still failed after repair attempt; using deterministic template fallback.")
        parsed = _deterministic_fallback_plan(user_request)

    # Backfill optional keys the model may have omitted so Plan validation
    # doesn't fail on a merely incomplete (but otherwise valid) response.
    parsed.setdefault("audience", None)
    parsed.setdefault("assumptions", [])
    for s in parsed["sections"]:
        s.setdefault("table_columns", None)

    try:
        return Plan(**parsed)
    except ValidationError as e:
        # The reply parsed as JSON but didn't satisfy the Plan schema (e.g. a
        # section missing "id"/"title"/"goal") -- same deterministic safety
        # net as an unparseable reply.
        logger.warning("Planner output parsed as JSON but failed Plan validation (%s); "
                        "using deterministic template fallback.", e)
        return Plan(**_deterministic_fallback_plan(user_request))
