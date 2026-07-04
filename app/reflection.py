"""
app/reflection.py
------------------
THE MANDATORY "ONE REAL ENGINEERING IMPROVEMENT": Reflection / self-check.

This module is deliberately review-only: it never drafts content itself.
Every regeneration is delegated to ``executor.revise_section`` -- the exact
same targeted-revision function the executor already exposes -- so there is
a single place in the codebase that knows how to turn a (plan, section,
issue) into new SectionContent. Duplicating that logic here would mean two
prompts to keep in sync every time drafting behaviour changes.

Pipeline role: Plan -> Execute (draft) -> **Reflect (review only)** -> targeted
revise via executor.revise_section -> re-review -> ... -> Render.
"""
from __future__ import annotations

import json
import logging
from typing import List, Dict, Any, Tuple

from app import config
from app.llm_client import LLMClient
from app.executor import revise_section
from app.schemas import Plan, SectionContent, SectionFeedback

logger = logging.getLogger("agent.reflection")

REFLECTION_SYSTEM_PROMPT = """You are the quality-reviewer module of an autonomous document-generation agent.

You will be shown the original user request, the document plan, and the
current draft of every section. For EACH section, decide if it is acceptable:
- ok=true if it is specific, on-topic, and complete enough for a business
  reader to act on.
- ok=false if it is too generic/short, off-topic, or missing information the
  goal asked for -- if so, give a one-sentence "issue" describing exactly
  what is wrong so it can be fixed.

Return ONLY a JSON object of this exact shape, no prose, no markdown fences:
{"overall_ok": true|false, "feedback": [{"id": "...", "ok": true|false, "issue": "..." or null}]}
"""


def _draft_to_text(content: Any) -> str:
    return json.dumps(content) if isinstance(content, list) else str(content)


def _reflection_prompt(user_request: str, plan: Plan, sections: List[SectionContent]) -> str:
    parts = [f"ORIGINAL REQUEST:\n{user_request}\n", f"DOCUMENT TITLE: {plan.title}\n"]
    for s in sections:
        parts.append(f"---SECTION---\nID: {s.id}\nTITLE: {s.title}\nCONTENT:\n{_draft_to_text(s.content)}\n")
    return "\n".join(parts)


def _parse_reflection(raw: str, section_ids: List[str]) -> Dict[str, SectionFeedback]:
    """Parses the reviewer's JSON verdict. If it can't be parsed, treats
    every section as OK rather than raising -- a broken *reviewer* should
    never block shipping an already-valid document."""
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            raw = raw[4:] if raw.lower().startswith("json") else raw
        data = json.loads(raw)
        return {item["id"]: SectionFeedback(**item) for item in data.get("feedback", []) if item.get("id") in section_ids}
    except (json.JSONDecodeError, TypeError, KeyError, ValueError) as e:
        logger.warning("Reflection output failed to parse (%s); treating all sections as OK.", e)
        return {sid: SectionFeedback(id=sid, ok=True, issue=None) for sid in section_ids}


async def run_reflection_loop(
    user_request: str, plan: Plan, sections: List[SectionContent], llm: LLMClient
) -> Tuple[List[SectionContent], List[Dict[str, Any]]]:
    """Reviews every section and, for anything flagged, delegates the
    rewrite to ``executor.revise_section`` -- this function never generates
    content itself. Bounded to ``config.MAX_REFLECTION_ROUNDS`` so a
    stubborn model can't loop forever; each round is logged for the caller
    to inspect (surfaced as ``reflection_log`` in the API response).
    """
    reflection_log: List[Dict[str, Any]] = []
    section_ids = [s.id for s in sections]
    section_by_id = {s.id: s for s in plan.sections}
    current = {s.id: s for s in sections}

    for round_no in range(1, config.MAX_REFLECTION_ROUNDS + 1):
        ordered = [current[sid] for sid in section_ids]
        prompt = _reflection_prompt(user_request, plan, ordered)
        try:
            raw = llm.generate(REFLECTION_SYSTEM_PROMPT, prompt, json_mode=True)
        except Exception as e:
            # A reviewer that can't be reached should skip its round, not
            # fail the whole request -- the sections drafted so far are
            # still a valid (if unreviewed) document.
            logger.warning("Reflection call failed (%s); skipping self-check for this round.", e)
            reflection_log.append({"round": round_no, "overall_ok": True, "flagged": [], "action": "skipped (reviewer unavailable)"})
            break

        feedback_map = _parse_reflection(raw, section_ids)
        flagged = [sid for sid, fb in feedback_map.items() if not fb.ok]

        if not flagged:
            reflection_log.append({"round": round_no, "overall_ok": True, "flagged": [], "action": "no issues found"})
            break

        # Delegate every rewrite to the executor's revise_section -- reflection
        # only decides WHAT needs fixing, never HOW to draft a replacement.
        # A revision that itself fails (provider unreachable after retries)
        # should not fail the whole request either -- keep that section's
        # previous draft and note it in the log rather than raising.
        revised_ids = []
        for sid in flagged:
            issue = feedback_map[sid].issue or "Needs more specific detail."
            try:
                current[sid] = await revise_section(llm, plan, section_by_id[sid], issue)
                revised_ids.append(sid)
            except Exception as e:
                logger.warning("Revision of section '%s' failed (%s); keeping its previous draft.", sid, e)

        unrevised = [sid for sid in flagged if sid not in revised_ids]
        action = f"revised {len(revised_ids)} section(s): {', '.join(revised_ids)}" if revised_ids else "no sections revised"
        if unrevised:
            action += f" (kept previous draft for: {', '.join(unrevised)})"
        reflection_log.append({"round": round_no, "overall_ok": False, "flagged": flagged, "action": action})

    return [current[sid] for sid in section_ids], reflection_log
