"""
tests/test_schemas.py
----------------------
Covers Step 3: the Pydantic data contracts, including the
request-validation guardrail on AgentRequest.
"""
import pytest
from pydantic import ValidationError

from app import config
from app.schemas import (
    AgentRequest,
    PlanSection,
    Plan,
    SectionContent,
    SectionFeedback,
    AgentResponse,
)


# ---- AgentRequest guardrails -------------------------------------------------

def test_agent_request_accepts_valid_text():
    req = AgentRequest(request="Create a project plan for our Q3 launch.")
    assert req.request == "Create a project plan for our Q3 launch."


def test_agent_request_strips_whitespace():
    req = AgentRequest(request="   Create a project plan for our launch.   ")
    assert req.request == "Create a project plan for our launch."


def test_agent_request_rejects_too_short():
    with pytest.raises(ValidationError):
        AgentRequest(request="hi")


def test_agent_request_rejects_blank():
    with pytest.raises(ValidationError):
        AgentRequest(request="       ")


def test_agent_request_rejects_too_long():
    with pytest.raises(ValidationError):
        AgentRequest(request="x" * (config.MAX_REQUEST_LENGTH + 1))


def test_agent_request_accepts_boundary_lengths():
    assert AgentRequest(request="x" * config.MIN_REQUEST_LENGTH).request == "x" * config.MIN_REQUEST_LENGTH
    assert AgentRequest(request="x" * config.MAX_REQUEST_LENGTH).request == "x" * config.MAX_REQUEST_LENGTH


# ---- Plan / PlanSection -------------------------------------------------------

def test_plan_section_defaults_table_columns_to_none():
    section = PlanSection(id="overview", title="Overview", goal="Explain the project.")
    assert section.table_columns is None


def test_plan_requires_sections():
    with pytest.raises(ValidationError):
        Plan(document_type="project_plan", title="My Plan")


def test_plan_builds_with_sections():
    plan = Plan(
        document_type="project_plan",
        title="Mobile App Launch",
        sections=[
            PlanSection(id="overview", title="Overview", goal="Summarise the project."),
            PlanSection(id="risks", title="Risks", goal="List risks.",
                        table_columns=["Risk", "Impact", "Mitigation"]),
        ],
    )
    assert plan.audience is None
    assert plan.assumptions == []
    assert len(plan.sections) == 2
    assert plan.sections[1].table_columns == ["Risk", "Impact", "Mitigation"]


# ---- SectionContent / SectionFeedback -----------------------------------------

def test_section_content_allows_str_or_list_content():
    prose = SectionContent(id="overview", title="Overview", content="Some prose.")
    table = SectionContent(id="risks", title="Risks", content=[{"Risk": "Delay"}],
                            table_columns=["Risk"])
    assert prose.revised is False
    assert isinstance(table.content, list)


def test_section_feedback_defaults_issue_to_none():
    fb = SectionFeedback(id="overview", ok=True)
    assert fb.issue is None


# ---- AgentResponse -------------------------------------------------------------

def test_agent_response_round_trip():
    response = AgentResponse(
        request_id="abc-123",
        status="completed",
        message="Generated a project plan titled 'Mobile App Launch'.",
        document_type="project_plan",
        title="Mobile App Launch",
        assumptions=["No budget was specified."],
        task_list=["Overview — Summarise the project."],
        reflection_log=[{"round": 1, "overall_ok": True, "flagged": [], "action": "no issues found"}],
        sections_generated=1,
        llm_provider_used="mock",
        download_url="/agent/download/abc-123",
    )
    dumped = response.model_dump()
    assert dumped["status"] == "completed"
    assert dumped["sections_generated"] == 1
