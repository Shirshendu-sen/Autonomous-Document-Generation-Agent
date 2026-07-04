"""
tests/test_templates.py
------------------------
Covers Step 4: the reference document-type templates, the deterministic
fallback-plan builder, and the keyword classifier used by the Mock LLM /
last-resort fallback.
"""
from app.templates import (
    DOCUMENT_TYPES,
    TEMPLATES,
    default_plan_dict,
    classify_keyword_fallback,
)


def test_every_document_type_has_a_template():
    for doc_type in DOCUMENT_TYPES:
        assert doc_type in TEMPLATES
        assert len(TEMPLATES[doc_type]) > 0


def test_template_sections_are_well_formed_tuples():
    for sections in TEMPLATES.values():
        for entry in sections:
            sid, title, cols = entry
            assert isinstance(sid, str) and sid
            assert isinstance(title, str) and title
            assert cols is None or (isinstance(cols, list) and all(isinstance(c, str) for c in cols))


def test_default_plan_dict_builds_valid_shape():
    plan = default_plan_dict("project_plan", "Mobile App Launch")
    assert plan["document_type"] == "project_plan"
    assert plan["title"] == "Mobile App Launch"
    assert plan["audience"] is None
    assert "fallback planner" in plan["assumptions"][0]
    assert len(plan["sections"]) == len(TEMPLATES["project_plan"])
    assert all("Mobile App Launch" in s["goal"] for s in plan["sections"])


def test_default_plan_dict_falls_back_to_business_report_for_unknown_type():
    plan = default_plan_dict("not_a_real_type", "Some Title")
    assert plan["document_type"] == "business_report"


def test_classify_keyword_fallback_matches_expected_types():
    cases = {
        "Write meeting minutes for our weekly sync.": "meeting_minutes",
        "Create an SOP for onboarding new hires.": "sop",
        "Draft a product spec with requirements.": "product_spec",
        "Document the system design and API design.": "technical_design",
        "Build a project plan with milestones.": "project_plan",
        "Quarterly performance report and analysis.": "business_report",
        "A proposal and rfp for the new vendor.": "proposal",
    }
    for text, expected in cases.items():
        assert classify_keyword_fallback(text) == expected


def test_classify_keyword_fallback_defaults_to_business_report():
    assert classify_keyword_fallback("Something totally unrelated to any keyword.") == "business_report"
