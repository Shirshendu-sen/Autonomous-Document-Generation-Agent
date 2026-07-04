"""
app/executor.py
----------------
Executes the plan produced by app.planner: drafts content for every section.

Sections are drafted independently and concurrently with ``asyncio.gather``,
each given the shared plan context (title, doc type, audience, assumptions)
plus its own goal. This trades a small amount of cross-section narrative
continuity for a large reduction in wall-clock latency -- a multi-section
document run sequentially against a free-tier/local LLM is noticeably slower
than the same document drafted in parallel. Lost coherence is partly
recovered by giving every section the same shared context rather than
nothing.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Union

from app.llm_client import LLMClient
from app.schemas import Plan, PlanSection, SectionContent

logger = logging.getLogger("agent.executor")

SECTION_SYSTEM_PROMPT = """You are drafting the content for ONE section of a business document.

Write clear, professional, specific content. Use the assumptions given to fill
any gaps -- never say you lack information; instead use a reasonable
placeholder consistent with the stated assumptions.

If TABLE COLUMNS are given, respond with ONLY a JSON array of 3-6 row objects,
one key per column name, no prose, no markdown fences.

If TABLE COLUMNS is None, respond with 2-4 well-developed paragraphs of plain
prose (no markdown headings, no bullet re-statement of the section title).
"""


def _section_prompt(plan: Plan, section: PlanSection, extra_instruction: str = "") -> str:
    """Builds the per-section prompt. Every section receives the same shared
    plan context so independently-drafted sections still stay thematically
    consistent even though they never see each other's text."""
    return (
        f"DOCUMENT TITLE: {plan.title}\n"
        f"DOCUMENT TYPE: {plan.document_type}\n"
        f"AUDIENCE: {plan.audience or 'general internal stakeholders'}\n"
        f"ASSUMPTIONS IN EFFECT: {'; '.join(plan.assumptions) if plan.assumptions else 'none'}\n"
        f"SECTION TITLE: {section.title}\n"
        f"SECTION GOAL: {section.goal}\n"
        f"TABLE COLUMNS: {section.table_columns if section.table_columns else 'None'}\n"
        f"{extra_instruction}"
    )


def _parse_section_output(raw: str, section: PlanSection) -> Union[str, List[Dict[str, Any]]]:
    """Table sections must come back as a JSON array of row objects; prose
    sections are used as-is. If a table section's output isn't valid JSON
    (a free/small model ignored the instruction), degrade gracefully to a
    single-row table containing the raw text rather than raising -- a
    malformed table is still better than a failed request."""
    raw = raw.strip()
    if section.table_columns:
        try:
            if raw.startswith("```"):
                raw = raw.strip("`")
                raw = raw[4:] if raw.lower().startswith("json") else raw
            rows = json.loads(raw)
            if isinstance(rows, list):
                return rows
        except json.JSONDecodeError:
            logger.warning("Table section '%s' did not return valid JSON; storing as single-row text.", section.id)
            return [{col: raw if i == 0 else "" for i, col in enumerate(section.table_columns)}]
    return raw


async def _draft_one(llm: LLMClient, plan: Plan, section: PlanSection) -> SectionContent:
    """Drafts a single section. The LLM call is a synchronous ``requests``
    call under the hood, so ``asyncio.to_thread`` moves it off the event
    loop -- this is what lets ``execute_plan`` run every section concurrently
    without needing an async HTTP client."""
    prompt = _section_prompt(plan, section)
    raw = await asyncio.to_thread(llm.generate, SECTION_SYSTEM_PROMPT, prompt, False)
    content = _parse_section_output(raw, section)
    return SectionContent(id=section.id, title=section.title, content=content,
                           table_columns=section.table_columns, revised=False)


async def execute_plan(plan: Plan, llm: LLMClient) -> List[SectionContent]:
    """Drafts every section in the plan concurrently.

    Note: if any section's LLM call exhausts its retries and raises
    ``LLMError``, ``asyncio.gather`` propagates it immediately -- this is
    intentional. A document missing a section due to a silently-swallowed
    failure would be worse than a clear, catchable error the caller can
    turn into a clean HTTP response.
    """
    tasks = [_draft_one(llm, plan, section) for section in plan.sections]
    return await asyncio.gather(*tasks)


async def revise_section(llm: LLMClient, plan: Plan, section: PlanSection, issue: str) -> SectionContent:
    """Re-drafts a single section that a later reflection pass flagged as
    weak, telling the model exactly what was wrong so the rewrite is
    targeted rather than a blind retry."""
    extra = (
        f"\nPREVIOUS DRAFT WAS FLAGGED BY QUALITY REVIEW: {issue}\n"
        "Write a more complete, specific replacement that resolves this issue."
    )
    prompt = _section_prompt(plan, section, extra_instruction=extra)
    raw = await asyncio.to_thread(llm.generate, SECTION_SYSTEM_PROMPT, prompt, False)
    content = _parse_section_output(raw, section)
    return SectionContent(id=section.id, title=section.title, content=content,
                           table_columns=section.table_columns, revised=True)
