"""
tests/test_reflection.py
--------------------------
Covers Step 8: the reflection / self-check loop. Verifies it is
review-only -- every regeneration is delegated to
``executor.revise_section`` and this module contains no drafting logic of
its own -- plus the round bound, graceful degradation when the reviewer
itself is unreachable, and unparseable-output handling.
"""
import asyncio

from app import config
from app import reflection
from app.executor import execute_plan
from app.llm_client import LLMClient, MockLLM
from app.reflection import run_reflection_loop, _parse_reflection
from app.schemas import Plan, PlanSection, SectionContent


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


# ---- happy path with the real Mock backend --------------------------------------

def test_reflection_flags_and_revises_short_prose_sections():
    plan = _make_plan([PlanSection(id="overview", title="Overview", goal="Summarise the project.")])
    llm = MockLLM()
    drafted = asyncio.run(execute_plan(plan, llm))

    revised, log = asyncio.run(run_reflection_loop("Launch the app.", plan, drafted, llm))

    assert revised[0].revised is True
    assert "(revised)" in revised[0].content
    assert log[0]["overall_ok"] is False
    assert "overview" in log[0]["flagged"]
    # Second round should find the (now longer) revised draft acceptable.
    assert log[-1]["overall_ok"] is True


def test_reflection_leaves_table_sections_alone():
    plan = _make_plan([
        PlanSection(id="risks", title="Risks", goal="List risks.",
                    table_columns=["Risk", "Impact", "Mitigation"]),
    ])
    llm = MockLLM()
    drafted = asyncio.run(execute_plan(plan, llm))
    revised, log = asyncio.run(run_reflection_loop("Launch the app.", plan, drafted, llm))

    assert revised[0].revised is False
    assert log[0]["overall_ok"] is True
    assert log[0]["flagged"] == []


# ---- reuse of executor.revise_section, not duplicated generation logic ----------

def test_reflection_delegates_every_rewrite_to_executor_revise_section(monkeypatch):
    plan = _make_plan([PlanSection(id="overview", title="Overview", goal="Summarise the project.")])
    llm = MockLLM()
    drafted = asyncio.run(execute_plan(plan, llm))

    calls = []
    original_revise = reflection.revise_section

    async def _spy(llm_arg, plan_arg, section_arg, issue_arg):
        calls.append((section_arg.id, issue_arg))
        return await original_revise(llm_arg, plan_arg, section_arg, issue_arg)

    monkeypatch.setattr(reflection, "revise_section", _spy)
    revised, log = asyncio.run(run_reflection_loop("Launch the app.", plan, drafted, llm))

    assert len(calls) >= 1
    assert calls[0][0] == "overview"
    assert revised[0].revised is True


# ---- bounded rounds --------------------------------------------------------------

class _AlwaysFlagsClient(LLMClient):
    """A reviewer that never approves anything -- used to prove the loop
    is bounded by MAX_REFLECTION_ROUNDS rather than looping forever."""

    name = "always-flags"

    def _call(self, system, user, json_mode):
        if "quality-reviewer" in system:
            return '{"overall_ok": false, "feedback": [{"id": "overview", "ok": false, "issue": "still weak"}]}'
        return "revised text " * 20  # long enough to not matter; reviewer always rejects anyway


def test_reflection_loop_is_bounded_by_max_rounds():
    plan = _make_plan([PlanSection(id="overview", title="Overview", goal="Summarise the project.")])
    llm = _AlwaysFlagsClient()
    drafted = asyncio.run(execute_plan(plan, llm))
    _, log = asyncio.run(run_reflection_loop("Launch the app.", plan, drafted, llm))

    assert len(log) == config.MAX_REFLECTION_ROUNDS
    assert log[-1]["overall_ok"] is False


# ---- broken reviewer never blocks shipping ---------------------------------------

class _ReviewerAlwaysFailsClient(LLMClient):
    name = "reviewer-fails"

    def _call(self, system, user, json_mode):
        if "quality-reviewer" in system:
            raise TimeoutError("reviewer unreachable")
        return "A perfectly fine short draft."


def test_reflection_skips_round_when_reviewer_unreachable():
    plan = _make_plan([PlanSection(id="overview", title="Overview", goal="Summarise the project.")])
    llm = _ReviewerAlwaysFailsClient()
    drafted = asyncio.run(execute_plan(plan, llm))
    revised, log = asyncio.run(run_reflection_loop("Launch the app.", plan, drafted, llm))

    assert len(log) == 1
    assert "skipped" in log[0]["action"]
    assert revised[0].revised is False  # untouched -- no regeneration was attempted


# ---- a failed revision never blocks shipping ---------------------------------------

class _RevisionAlwaysFailsClient(LLMClient):
    """The reviewer successfully flags a section, but every subsequent
    revision attempt fails -- proves a failed *revision* (as opposed to a
    failed *review*) also doesn't crash the whole request; the section's
    previous draft is kept instead."""

    name = "revision-fails"

    def _call(self, system, user, json_mode):
        if "quality-reviewer" in system:
            return '{"overall_ok": false, "feedback": [{"id": "overview", "ok": false, "issue": "too short"}]}'
        raise TimeoutError("revision call unreachable")


def test_reflection_keeps_previous_draft_when_revision_fails():
    plan = _make_plan([PlanSection(id="overview", title="Overview", goal="Summarise the project.")])
    original = SectionContent(id="overview", title="Overview", content="Original short draft.", revised=False)
    llm = _RevisionAlwaysFailsClient()

    revised, log = asyncio.run(run_reflection_loop("Launch the app.", plan, [original], llm))

    assert revised[0].content == "Original short draft."
    assert revised[0].revised is False
    assert "overview" in log[0]["flagged"]
    assert "kept previous draft for: overview" in log[0]["action"]


# ---- unparseable reviewer output --------------------------------------------------

def test_parse_reflection_treats_unparseable_output_as_all_ok():
    feedback_map = _parse_reflection("not valid json at all", ["overview", "risks"])
    assert feedback_map["overview"].ok is True
    assert feedback_map["risks"].ok is True
