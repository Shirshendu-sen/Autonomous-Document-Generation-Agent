"""
tests/test_main.py
--------------------
Covers Step 11 (FastAPI app) and the complete end-to-end pipeline:
Request -> Planner -> Executor -> Reflection (review only) -> targeted
revise of flagged sections -> DOCX -> Response.

Also contains the two required assignment test inputs (one standard, one
complex/ambiguous request), run through the full in-process pipeline via
FastAPI's TestClient against LLM_PROVIDER=mock -- no network access or API
key required, matching the guide's own test/demo approach.
"""
import os

os.environ.setdefault("LLM_PROVIDER", "mock")

import json

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ---- basic health / guardrail ----------------------------------------------------

def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_rejects_too_short_request():
    resp = client.post("/agent", json={"request": "hi"})
    assert resp.status_code == 422


# ---- unknown request_id on the download / plan endpoints -------------------------

def test_download_unknown_request_id_returns_404():
    resp = client.get("/agent/download/does-not-exist")
    assert resp.status_code == 404


def test_plan_endpoint_unknown_request_id_returns_404():
    resp = client.get("/agent/plan/does-not-exist")
    assert resp.status_code == 404


# ---- full pipeline sanity checks --------------------------------------------------

def test_full_pipeline_produces_downloadable_docx_and_inspectable_plan():
    resp = client.post("/agent", json={
        "request": "Write meeting minutes for our weekly product sync, covering decisions and action items."
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["sections_generated"] > 0
    assert data["llm_provider_used"] == "mock"

    dl = client.get(data["download_url"])
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert dl.content[:2] == b"PK"  # a .docx is a zip archive

    plan_resp = client.get(f"/agent/plan/{data['request_id']}")
    assert plan_resp.status_code == 200
    plan_data = plan_resp.json()
    assert plan_data["plan"]["title"] == data["title"]
    assert plan_data["reflection_log"] == data["reflection_log"]


def test_reflection_loop_ran_and_is_reported():
    resp = client.post("/agent", json={"request": "Write meeting minutes for our weekly product sync."})
    data = resp.json()
    assert "reflection_log" in data
    assert len(data["reflection_log"]) >= 1


# ---- Required assignment test case 1: standard business request ------------------

def test_required_case_1_standard_business_request():
    request_text = (
        "Create a project plan for launching our new mobile banking app in Q3. "
        "Include a timeline, team roles, and key risks."
    )
    resp = client.post("/agent", json={"request": request_text})
    assert resp.status_code == 200
    data = resp.json()

    print("\n" + "=" * 90)
    print("REQUIRED TEST CASE 1: standard business request")
    print("=" * 90)
    print(f"REQUEST           : {request_text}")
    print(f"LLM provider used : {data['llm_provider_used']}")
    print(f"Detected doc type : {data['document_type']}")
    print(f"Title             : {data['title']}")
    print("--- Agent's self-generated task list (autonomous plan) ---")
    for i, task in enumerate(data["task_list"], 1):
        print(f"  {i}. {task}")
    print("--- Reflection / self-check log ---")
    print(json.dumps(data["reflection_log"], indent=2))

    assert data["status"] == "completed"
    assert data["document_type"] == "project_plan"
    assert len(data["task_list"]) > 0

    dl = client.get(data["download_url"])
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("application/vnd.openxmlformats")


# ---- Required assignment test case 2: complex / ambiguous request ----------------

def test_required_case_2_complex_ambiguous_request():
    request_text = (
        "We need some kind of document for the new client onboarding thing the ops "
        "team mentioned in standup. Make it look professional. I don't have all the "
        "details yet but leadership wants to review it Friday."
    )
    resp = client.post("/agent", json={"request": request_text})
    assert resp.status_code == 200
    data = resp.json()

    print("\n" + "=" * 90)
    print("REQUIRED TEST CASE 2: complex / ambiguous request")
    print("=" * 90)
    print(f"REQUEST           : {request_text}")
    print(f"LLM provider used : {data['llm_provider_used']}")
    print(f"Detected doc type : {data['document_type']}")
    print(f"Title             : {data['title']}")
    print("--- Agent's self-generated task list (autonomous plan) ---")
    for i, task in enumerate(data["task_list"], 1):
        print(f"  {i}. {task}")
    print("--- Assumptions the agent made to fill information gaps ---")
    for a in data["assumptions"]:
        print(f"  - {a}")
    print("--- Reflection / self-check log ---")
    print(json.dumps(data["reflection_log"], indent=2))

    # This request names no document type, no budget, and no firm scope --
    # the agent must not ask a follow-up question; it must assume and proceed.
    assert data["status"] == "completed"
    assert len(data["assumptions"]) > 0

    dl = client.get(data["download_url"])
    assert dl.status_code == 200
    assert dl.headers["content-type"].startswith("application/vnd.openxmlformats")
