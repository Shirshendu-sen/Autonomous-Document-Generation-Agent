"""
app/templates.py
-----------------
Reference section structures for each supported business-document type.
"""

DOCUMENT_TYPES = [
    "proposal", "meeting_minutes", "project_plan", "business_report",
    "technical_design", "sop", "product_spec",
]

TEMPLATES = {
    "proposal": [
        ("executive_summary", "Executive Summary", None),
        ("background", "Background & Problem Statement", None),
        ("proposed_solution", "Proposed Solution", None),
        ("scope", "Scope of Work", None),
        ("timeline", "Timeline & Milestones", ["Milestone", "Owner", "Due Date"]),
        ("budget", "Budget & Cost Estimate", ["Item", "Description", "Cost (USD)"]),
        ("team", "Team & Roles", ["Name", "Role", "Responsibility"]),
        ("risks", "Risks & Mitigation", ["Risk", "Impact", "Mitigation"]),
        ("conclusion", "Conclusion & Next Steps", None),
    ],
    "meeting_minutes": [
        ("meeting_info", "Meeting Information", ["Field", "Detail"]),
        ("attendees", "Attendees", ["Name", "Role"]),
        ("agenda", "Agenda", None),
        ("discussion", "Discussion Summary", None),
        ("decisions", "Decisions Made", None),
        ("action_items", "Action Items", ["Action", "Owner", "Due Date", "Status"]),
        ("next_meeting", "Next Meeting", None),
    ],
    "project_plan": [
        ("overview", "Overview", None),
        ("objectives", "Objectives", None),
        ("scope", "Scope", None),
        ("milestones", "Milestones", ["Milestone", "Owner", "Due Date", "Status"]),
        ("resources", "Resources & Staffing", ["Resource", "Role", "Allocation"]),
        ("risks", "Risks & Mitigation", ["Risk", "Impact", "Mitigation"]),
        ("success_criteria", "Success Criteria", None),
    ],
    "business_report": [
        ("executive_summary", "Executive Summary", None),
        ("introduction", "Introduction", None),
        ("findings", "Findings & Analysis", None),
        ("metrics", "Key Metrics", ["Metric", "Value", "Trend"]),
        ("recommendations", "Recommendations", None),
        ("conclusion", "Conclusion", None),
    ],
    "technical_design": [
        ("overview", "Overview", None),
        ("goals_non_goals", "Goals & Non-Goals", None),
        ("architecture", "Architecture", None),
        ("components", "Key Components", ["Component", "Responsibility"]),
        ("data_flow", "Data Flow", None),
        ("api_design", "API Design", ["Endpoint", "Method", "Description"]),
        ("tradeoffs", "Tradeoffs & Alternatives Considered", None),
        ("risks", "Risks & Mitigation", ["Risk", "Mitigation"]),
        ("rollout_plan", "Rollout Plan", None),
    ],
    "sop": [
        ("purpose", "Purpose", None),
        ("scope", "Scope", None),
        ("roles", "Roles & Responsibilities", ["Role", "Responsibility"]),
        ("procedure", "Procedure", None),
        ("tools_materials", "Tools & Materials", None),
        ("safety_compliance", "Safety & Compliance Notes", None),
        ("revision_history", "Revision History", ["Version", "Date", "Author", "Changes"]),
    ],
    "product_spec": [
        ("overview", "Overview", None),
        ("problem_statement", "Problem Statement", None),
        ("goals_metrics", "Goals & Success Metrics", ["Goal", "Metric", "Target"]),
        ("requirements", "Requirements", ["ID", "Requirement", "Priority"]),
        ("feature_details", "Feature Details", None),
        ("out_of_scope", "Out of Scope", None),
        ("timeline", "Timeline", ["Phase", "Target Date"]),
        ("open_questions", "Open Questions", None),
    ],
}


def default_plan_dict(document_type: str, title: str) -> dict:
    """Deterministic fallback plan used if the LLM's plan can't be parsed."""
    doc_type = document_type if document_type in TEMPLATES else "business_report"
    sections = [
        {"id": sid, "title": stitle, "goal": f"Cover {stitle.lower()} for: {title}", "table_columns": cols}
        for sid, stitle, cols in TEMPLATES[doc_type]
    ]
    return {
        "document_type": doc_type,
        "title": title,
        "audience": None,
        "assumptions": ["Generated with the deterministic fallback planner because the LLM plan could not be parsed."],
        "sections": sections,
    }


def classify_keyword_fallback(user_request: str) -> str:
    """Very cheap keyword heuristic, used only by the Mock LLM / last-resort fallback."""
    text = user_request.lower()
    if any(k in text for k in ["meeting", "minutes", "attendee", "agenda"]):
        return "meeting_minutes"
    if any(k in text for k in ["sop", "standard operating procedure", "procedure for", "checklist", "onboarding", "process for"]):
        return "sop"
    if any(k in text for k in ["spec", "requirements", "user story", "feature"]):
        return "product_spec"
    if any(k in text for k in ["architecture", "technical design", "system design", "api design"]):
        return "technical_design"
    if any(k in text for k in ["project plan", "roadmap", "launch plan", "milestones"]):
        return "project_plan"
    if any(k in text for k in ["report", "analysis", "quarterly", "performance"]):
        return "business_report"
    if any(k in text for k in ["proposal", "pitch", "quote", "rfp"]):
        return "proposal"
    return "business_report"
