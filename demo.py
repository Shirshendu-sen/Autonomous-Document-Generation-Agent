"""
demo.py
-------
Drives the two required assignment test cases against a *running* server and
prints the agent's self-generated task list and reflection log -- this is
the human-watchable counterpart to tests/test_main.py's assertion-based
versions of the same two cases.

Usage:
    uvicorn app.main:app --reload      # terminal 1
    python demo.py                     # terminal 2
"""
import json, pathlib, sys
import requests

BASE_URL = "http://localhost:8000"

TEST_CASES = {
    "1_standard_business_request": (
        "Create a project plan for launching our new mobile banking app in Q3. "
        "Include a timeline, team roles, and key risks."
    ),
    "2_complex_ambiguous_request": (
        "We need some kind of document for the new client onboarding thing the ops "
        "team mentioned in standup. Make it look professional. I don't have all the "
        "details yet but leadership wants to review it Friday."
    ),
}


def run_case(name, request_text):
    print("=" * 90); print(f"TEST CASE: {name}"); print(f"REQUEST  : {request_text}"); print("=" * 90)
    resp = requests.post(f"{BASE_URL}/agent", json={"request": request_text}, timeout=120)
    if resp.status_code != 200:
        print(f"!! Request failed [{resp.status_code}]: {resp.text}"); return

    data = resp.json()
    print(f"\nLLM provider used : {data['llm_provider_used']}")
    print(f"Detected doc type : {data['document_type']}")
    print(f"Title             : {data['title']}")
    print("\n--- Agent's self-generated task list (autonomous plan) ---")
    for i, task in enumerate(data["task_list"], 1):
        print(f"  {i}. {task}")
    print("\n--- Assumptions the agent made to fill information gaps ---")
    for a in data["assumptions"]:
        print(f"  - {a}")
    print("\n--- Reflection / self-check log ---")
    print(json.dumps(data["reflection_log"], indent=2))

    out_dir = pathlib.Path("demo_output"); out_dir.mkdir(exist_ok=True)
    doc_resp = requests.get(f"{BASE_URL}{data['download_url']}", timeout=30)
    (out_dir / f"{name}.docx").write_bytes(doc_resp.content)
    print(f"\nSaved document -> {(out_dir / f'{name}.docx').resolve()}\n")


if __name__ == "__main__":
    try:
        requests.get(f"{BASE_URL}/health", timeout=3)
    except requests.exceptions.ConnectionError:
        print("Server is not running. Start it first with:\n  uvicorn app.main:app --reload")
        sys.exit(1)
    for name, text in TEST_CASES.items():
        run_case(name, text)
