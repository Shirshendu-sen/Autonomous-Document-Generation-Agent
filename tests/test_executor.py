"""
tests/test_executor.py
------------------------
Covers Step 7: concurrent section drafting, table vs. prose parsing, the
targeted single-section revision path, and error propagation when an LLM
call exhausts its retries mid-execution.
"""
import asyncio

import pytest

from app.executor import execute_plan, revise_section, _parse_section_output, _section_prompt
from app.llm_client import LLMClient, LLMError, MockLLM
from app.schemas import Plan, PlanSection


def _make_plan(sections):
    return Plan(
        document_type="project_plan",
        title="Mobile App Launch",
        audience="Leadership",
        assumptions=["No budget was specified."],
        sections=sections,
    )


# Backoff sleeps are patched out for every test via the autouse
# no_real_llm_sleep fixture in tests/conftest.py.


# ---- concurrent drafting with the real Mock backend ---------------------------

def test_execute_plan_drafts_every_section():
    plan = _make_plan([
        PlanSection(id="overview", title="Overview", goal="Summarise the project."),
        PlanSection(id="risks", title="Risks", goal="List risks.",
                    table_columns=["Risk", "Impact", "Mitigation"]),
    ])
    sections = asyncio.run(execute_plan(plan, MockLLM()))

    assert len(sections) == 2
    prose, table = sections
    assert isinstance(prose.content, str) and len(prose.content) > 0
    assert prose.revised is False

    assert isinstance(table.content, list)
    assert set(table.content[0].keys()) == {"Risk", "Impact", "Mitigation"}


def test_execute_plan_preserves_section_order():
    plan = _make_plan([
        PlanSection(id=f"s{i}", title=f"Section {i}", goal="Goal.") for i in range(5)
    ])
    sections = asyncio.run(execute_plan(plan, MockLLM()))
    assert [s.id for s in sections] == [f"s{i}" for i in range(5)]


# ---- revision path --------------------------------------------------------------

def test_revise_section_marks_revised_and_uses_flagged_issue():
    plan = _make_plan([PlanSection(id="overview", title="Overview", goal="Summarise the project.")])
    revised = asyncio.run(revise_section(MockLLM(), plan, plan.sections[0], "Too brief."))
    assert revised.revised is True
    assert "(revised)" in revised.content


# ---- prompt construction --------------------------------------------------------

def test_section_prompt_includes_shared_plan_context():
    plan = _make_plan([PlanSection(id="overview", title="Overview", goal="Summarise the project.")])
    prompt = _section_prompt(plan, plan.sections[0])
    assert "Mobile App Launch" in prompt
    assert "Leadership" in prompt
    assert "No budget was specified." in prompt
    assert "TABLE COLUMNS: None" in prompt


def test_section_prompt_includes_extra_instruction_for_revisions():
    plan = _make_plan([PlanSection(id="overview", title="Overview", goal="Summarise.")])
    prompt = _section_prompt(plan, plan.sections[0], extra_instruction="FIX THIS")
    assert "FIX THIS" in prompt


# ---- table-output parsing / degradation ----------------------------------------

def test_parse_section_output_returns_prose_as_is():
    section = PlanSection(id="overview", title="Overview", goal="Summarise.")
    assert _parse_section_output("Some prose text.", section) == "Some prose text."


def test_parse_section_output_parses_valid_table_json():
    section = PlanSection(id="risks", title="Risks", goal="List risks.", table_columns=["Risk"])
    rows = _parse_section_output('[{"Risk": "Delay"}]', section)
    assert rows == [{"Risk": "Delay"}]


def test_parse_section_output_degrades_gracefully_for_invalid_table_json():
    section = PlanSection(id="risks", title="Risks", goal="List risks.",
                           table_columns=["Risk", "Impact"])
    rows = _parse_section_output("not valid json", section)
    assert rows == [{"Risk": "not valid json", "Impact": ""}]


def test_parse_section_output_strips_code_fences_from_table_json():
    section = PlanSection(id="risks", title="Risks", goal="List risks.", table_columns=["Risk"])
    rows = _parse_section_output('```json\n[{"Risk": "Delay"}]\n```', section)
    assert rows == [{"Risk": "Delay"}]


# ---- error propagation -----------------------------------------------------------

class _AlwaysRaisesClient(LLMClient):
    name = "always-raises"

    def _call(self, system, user, json_mode):
        raise TimeoutError("simulated failure")


def test_execute_plan_propagates_llm_error_on_persistent_failure():
    plan = _make_plan([PlanSection(id="overview", title="Overview", goal="Summarise.")])
    with pytest.raises(LLMError):
        asyncio.run(execute_plan(plan, _AlwaysRaisesClient()))
