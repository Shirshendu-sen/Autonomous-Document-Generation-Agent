"""
app/schemas.py
--------------
Pydantic models used for:
  1) Validating the incoming API request (guardrails).
  2) Giving every internal stage a typed, predictable data contract.
  3) Shaping the final JSON returned by POST /agent.
"""
from __future__ import annotations
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator

from app import config


class AgentRequest(BaseModel):
    request: str = Field(..., description="Natural language description of the document the user needs.")

    @field_validator("request")
    @classmethod
    def not_blank_and_reasonable_length(cls, v: str) -> str:
        v = v.strip()
        if len(v) < config.MIN_REQUEST_LENGTH:
            raise ValueError("Request is too short to plan a document from. Please add more detail.")
        if len(v) > config.MAX_REQUEST_LENGTH:
            raise ValueError(f"Request is too long (max {config.MAX_REQUEST_LENGTH} characters). Please summarise.")
        return v


class PlanSection(BaseModel):
    id: str
    title: str
    goal: str
    table_columns: Optional[List[str]] = None  # set -> this section renders as a Word table


class Plan(BaseModel):
    document_type: str
    title: str
    audience: Optional[str] = None
    assumptions: List[str] = Field(default_factory=list)
    sections: List[PlanSection]


class SectionContent(BaseModel):
    id: str
    title: str
    content: Any  # str for prose sections, List[Dict[str, str]] for table sections
    table_columns: Optional[List[str]] = None
    revised: bool = False


class SectionFeedback(BaseModel):
    id: str
    ok: bool
    issue: Optional[str] = None


class AgentResponse(BaseModel):
    request_id: str
    status: str
    message: str
    document_type: str
    title: str
    assumptions: List[str]
    task_list: List[str]                  # the agent's self-generated plan, human readable
    reflection_log: List[Dict[str, Any]]  # what the self-check found and fixed, per round
    sections_generated: int
    llm_provider_used: str
    download_url: str
