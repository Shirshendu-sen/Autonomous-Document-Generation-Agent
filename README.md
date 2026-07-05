# 🤖 Autonomous Document-Generation Agent

![Python](https://img.shields.io/badge/Python-3.14-blue?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-e92063?logo=pydantic&logoColor=white)
![Tests](https://img.shields.io/badge/tests-88%20passed-brightgreen)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

A FastAPI service that takes a single natural-language request and, with **no human in the loop**, autonomously:

1. **Plans** its own task list (document type, title, sections, assumptions),
2. **Executes** that plan by drafting every section concurrently,
3. **Reflects** on its own output, flags weak sections, and rewrites only those, then
4. **Renders** a polished `.docx` — cover page, table of contents, styled headings, real Word tables, header/footer.

The LLM backend is swappable behind one interface — **Groq** (free-tier hosted), **Ollama** (fully local), or **Mock** (deterministic offline stub, the default) — so the whole pipeline runs with zero setup and zero API keys.

> Full step-by-step build rationale lives in [`../autonomous_agent_build_guide.md`](../autonomous_agent_build_guide.md).

---

## ✨ Features

- **Autonomous planning** — the agent decides document type, title, audience, and section structure itself; it never asks a follow-up question, it states an explicit assumption instead.
- **Concurrent section drafting** — every section is drafted in parallel via `asyncio.gather` for low latency, sharing common plan context to stay thematically consistent.
- **Reflection / self-check loop** — a review-only pass re-reads every section against the original request, flags weak ones, and delegates a targeted rewrite — bounded to a configurable number of rounds.
- **Pluggable LLM backends** — Groq, Ollama, or an offline Mock, selected by one environment variable, with automatic fallback to Mock if the configured provider is unreachable.
- **Graceful degradation everywhere** — unparseable planner JSON, a schema-invalid plan, a failed revision, or an unreachable reviewer all degrade to a safe fallback instead of crashing the request.
- **Polished `.docx` output** — cover page, real Word `TOC` field, styled headings, shaded-header tables for tabular sections, header/footer with page numbers, and inline notes on any section the self-check revised.
- **Full transparency** — the agent's task list, stated assumptions, and per-round reflection log are all returned in the API response and independently inspectable via `GET /agent/plan/{id}`.
- **7 supported business-document types** — proposal, meeting minutes, project plan, business report, technical design, SOP, product spec.

---

## 🏗️ Architecture

```
POST /agent {"request": "..."}
        │
        ▼
 ┌─────────────┐   1. PLAN     → decide doc type, title, assumptions, section list (its own TODO list)
 │  planner.py │
 └─────────────┘
        │
        ▼
 ┌─────────────┐   2. EXECUTE  → draft every section concurrently (asyncio.gather)
 │ executor.py │
 └─────────────┘
        │
        ▼
 ┌───────────────┐ 3. REFLECT   → self-review each section; auto-revise anything flagged
 │ reflection.py │              (bounded rounds) ⭐ the mandatory engineering improvement
 └───────────────┘
        │
        ▼
 ┌─────────────────┐ 4. RENDER  → build a polished .docx (cover page, TOC, styled
 │ doc_generator.py│              headings, real Word tables, header/footer)
 └─────────────────┘
        │
        ▼
   JSON response (plan + reflection log + download_url) + the .docx file
```

---

## 🧰 Tech Stack

| Concern | Choice | Why |
|---|---|---|
| API framework | **FastAPI** | async-native, Pydantic validation + OpenAPI docs for free |
| Server | **Uvicorn** | standard ASGI server for FastAPI |
| LLM | **Groq** / **Ollama** / **Mock** | one of three interchangeable backends behind a single interface — runs with zero setup (Mock), a local model (Ollama), or a fast hosted free model (Groq) |
| Word generation | **python-docx** | pure Python, no external binary dependency, full control over styles/tables/fields |
| Validation | **Pydantic v2** | typed contracts between every pipeline stage, not just at the API boundary |
| HTTP calls to LLMs | **requests** | Groq's API is a plain OpenAI-compatible REST endpoint, Ollama exposes a local REST API — no SDK needed |
| Testing | **pytest + FastAPI `TestClient`** | in-process tests, no network required |

---

## 📁 Project Structure

```
agent_project/
├── app/
│   ├── __init__.py
│   ├── config.py          # env-based settings
│   ├── schemas.py          # Pydantic request/response/plan contracts
│   ├── templates.py        # reference section structures per document type
│   ├── llm_client.py        # Groq / Ollama / Mock behind one interface
│   ├── planner.py           # autonomous plan generation
│   ├── executor.py          # concurrent section drafting + targeted revision
│   ├── reflection.py         # review-only self-check loop (reuses executor.revise_section)
│   ├── doc_generator.py      # python-docx rendering
│   ├── storage.py            # in-memory request_id -> file/plan registry
│   └── main.py                # FastAPI app & routes
├── tests/
│   ├── test_config.py
│   ├── test_schemas.py
│   ├── test_templates.py
│   ├── test_llm_client.py
│   ├── test_planner.py
│   ├── test_executor.py
│   ├── test_reflection.py
│   ├── test_doc_generator.py
│   ├── test_storage.py
│   └── test_main.py        # endpoint tests + the two required demonstration cases
├── demo.py                 # live run of the two required test cases against a running server
├── demo_output/             # .docx files saved by demo.py
├── generated_docs/          # output dir used by the live API, auto-created by config.py
├── requirements.txt
└── .env.example
```

---

## ⚙️ Installation

```bash
git clone <this-repo>
cd agent_project
python -m venv .venv
source .venv/Scripts/activate      # Windows Git Bash; use .venv\Scripts\activate.bat for cmd.exe
pip install -r requirements.txt
```

**Dependencies** (`requirements.txt`):

```txt
fastapi==0.115.0
uvicorn[standard]==0.30.6
pydantic==2.13.4
python-docx==1.1.2
requests==2.32.3
python-dotenv==1.0.1
pytest==8.3.3
httpx==0.27.2
```

---

## 🔐 Environment Setup (`.env`)

```bash
cp .env.example .env   # optional — defaults to LLM_PROVIDER=mock, no keys required
```

`.env.example`:

```bash
# one of: groq | ollama | mock
LLM_PROVIDER=mock

# --- Groq (free tier: https://console.groq.com) -----------------------------
GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

# --- Ollama (fully local: https://ollama.com) --------------------------------
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama3

# --- Agent behaviour ----------------------------------------------------------
MAX_REFLECTION_ROUNDS=2
LLM_MAX_RETRIES=4
REQUEST_TIMEOUT_SECONDS=30
LLM_MAX_CONCURRENCY=1
```

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `mock` | `groq`, `ollama`, or `mock` — falls back to `mock` automatically if the chosen provider is unreachable/misconfigured |
| `GROQ_API_KEY` | *(empty)* | required only when `LLM_PROVIDER=groq` |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model name |
| `OLLAMA_HOST` | `http://localhost:11434` | local Ollama server URL |
| `OLLAMA_MODEL` | `llama3` | Ollama model name |
| `MAX_REFLECTION_ROUNDS` | `2` | max self-check/revise rounds before returning |
| `LLM_MAX_RETRIES` | `4` | retry attempts per LLM call — honours the provider's `Retry-After` header on 429s, falls back to exponential backoff otherwise |
| `REQUEST_TIMEOUT_SECONDS` | `30` | per-LLM-call HTTP timeout |
| `LLM_MAX_CONCURRENCY` | `1` | max concurrent section-drafting LLM calls; Groq free-tier keys are commonly capped around 6000 tokens/minute, and a single multi-section document can use most of that alone, so this is kept low to avoid bursting past the limit |

**Using Groq:** sign up at [console.groq.com](https://console.groq.com), create an API key, then set `GROQ_API_KEY` and `LLM_PROVIDER=groq`.
**Using Ollama:** install from [ollama.com](https://ollama.com), `ollama pull llama3`, `ollama serve`, then set `LLM_PROVIDER=ollama`.

---

## ▶️ Running the Application

```bash
uvicorn app.main:app --reload
# Swagger docs auto-generated at http://localhost:8000/docs
```

### Live demo (drives the two required test cases against the running server)

```bash
uvicorn app.main:app --reload      # terminal 1
python demo.py                     # terminal 2
```

`demo.py` posts both required test cases, prints the agent's self-generated task list, stated assumptions, and reflection log, and saves each generated `.docx` to `demo_output/`.

---

## ✅ Running Tests

```bash
python -m pytest -v
```

**Current result: 84 passed.** All tests run against mocks/fakes (`MockLLM`, plus hand-written `LLMClient` subclasses for retry/failure scenarios) — no network access, no `GROQ_API_KEY`, and no local Ollama server required. `tests/test_main.py` includes the two required assignment test cases run through the full in-process pipeline via FastAPI's `TestClient` (pass `-s` to see the printed task list/reflection log for each).

---

## 🌐 API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `POST` | `/agent` | Plan, draft, self-check, and render a business document from a natural-language request |
| `GET` | `/agent/download/{request_id}` | Download the generated `.docx` for a previous request |
| `GET` | `/agent/plan/{request_id}` | Inspect the exact plan and reflection log behind a previous request |

---

## 📨 Example Requests & Responses

### `POST /agent`

**Request:**

```json
{
  "request": "Create a project plan for launching our new mobile banking app in Q3. Include a timeline, team roles, and key risks."
}
```

**Response `200 OK`:**

```json
{
  "request_id": "b3f1c2e4-...",
  "status": "completed",
  "message": "Generated a project plan titled 'Project Plan: Project Plan For Launching Our New Mobile Banking App'.",
  "document_type": "project_plan",
  "title": "Project Plan: Project Plan For Launching Our New Mobile Banking App",
  "assumptions": [
    "Request was specific enough that no major assumptions were required."
  ],
  "task_list": [
    "Overview — Explain overview relevant to: ...",
    "Objectives — Explain objectives relevant to: ...",
    "Scope — Explain scope relevant to: ...",
    "Milestones — Explain milestones relevant to: ...",
    "Resources & Staffing — Explain resources & staffing relevant to: ...",
    "Risks & Mitigation — Explain risks & mitigation relevant to: ...",
    "Success Criteria — Explain success criteria relevant to: ..."
  ],
  "reflection_log": [
    { "round": 1, "overall_ok": false,
      "flagged": ["overview", "objectives", "scope", "success_criteria"],
      "action": "revised 4 section(s): overview, objectives, scope, success_criteria" },
    { "round": 2, "overall_ok": true, "flagged": [], "action": "no issues found" }
  ],
  "sections_generated": 7,
  "llm_provider_used": "mock",
  "download_url": "/agent/download/b3f1c2e4-..."
}
```

**Invalid request** (too short, `< 8` chars) → `422 Unprocessable Entity`.

### `GET /agent/download/{request_id}`

Returns the binary `.docx` (`application/vnd.openxmlformats-officedocument.wordprocessingml.document`), or `404` if `request_id` is unknown / the server has restarted since (storage is in-memory).

### `GET /agent/plan/{request_id}`

```json
{
  "plan": { "document_type": "project_plan", "title": "...", "audience": null, "assumptions": [...], "sections": [...] },
  "reflection_log": [ { "round": 1, "overall_ok": false, "flagged": [...], "action": "..." } ]
}
```

---

## 🔄 Autonomous Agent Workflow

1. **Request** — `POST /agent {"request": "..."}` is validated by `AgentRequest` (rejects blank / `< 8` / `> 4000` character requests with a clean `422` before any LLM call is made).
2. **Plan** (`app/planner.py`) — the LLM decides the document type, title, audience, explicit assumptions, and an ordered section list — the agent's own TODO list. It is instructed to **never ask a follow-up question**; it states an assumption and proceeds instead. Four-tier resilience against unreliable model output: (1) parse the reply directly, (2) send the exact parse error back for one self-correction attempt, (3) fall back to a deterministic template plan (`app/templates.py`) if it still can't be parsed, (4) fall back to the same template if the parsed JSON is schema-invalid.
3. **Execute** (`app/executor.py`) — every section is drafted **concurrently** via `asyncio.gather` (each LLM call moved off the event loop with `asyncio.to_thread`), sharing the same plan context (title, audience, assumptions) so independently-drafted sections stay thematically consistent.
4. **Reflect** (`app/reflection.py`) — see below.
5. **Render** (`app/doc_generator.py`) — builds the final `.docx`.
6. **Response** — `AgentResponse` returns the task list, assumptions, reflection log, and a `download_url`; storage (`app/storage.py`) keeps an in-memory record for later download/inspection.

---

## 🔍 Reflection / Self-Check Implementation

`app/reflection.py` is **the mandatory engineering improvement**. After every section is drafted, the agent switches role to a **quality reviewer**: it re-reads each section against the original request and, for anything flagged, delegates the rewrite to the exact same `executor.revise_section()` the executor already exposes — this module contains no drafting logic of its own.

- **Bounded** to `MAX_REFLECTION_ROUNDS` (default `2`) so a stubborn model can't loop forever.
- **Fails safe** — a reviewer call that can't be reached skips its round (logged as `"skipped (reviewer unavailable)"`) rather than failing the request; a revision that itself fails keeps the section's previous draft rather than raising. A broken reviewer or a transient failure should never block shipping an already-valid document.
- **Fully logged** — every round is appended to `reflection_log`, returned in the API response and inspectable via `GET /agent/plan/{id}`.
- **Visible in the document** — any section revised by the self-check is marked with a small *"(refined by the agent's self-check pass)"* note in the rendered `.docx`.

---

## 🧪 Two Demonstration Test Cases

Both are driven live by `demo.py` (and asserted in `tests/test_main.py`).

**Case 1 — standard business request:**
> *"Create a project plan for launching our new mobile banking app in Q3. Include a timeline, team roles, and key risks."*

The agent detects `project_plan`, drafts all 7 sections concurrently, and its self-check flags and revises 4 thin first-draft sections in round 1 before passing clean in round 2.

**Case 2 — complex / ambiguous request** (no document type, budget, or firm deadline given):
> *"We need some kind of document for the new client onboarding thing the ops team mentioned in standup. Make it look professional. I don't have all the details yet but leadership wants to review it Friday."*

The agent independently decides this is an `sop` (a process document), states explicit assumptions instead of asking a follow-up question (e.g. *"No budget was specified, so illustrative placeholder figures are used."*), and its self-check catches and rewrites 5 of 7 thin sections before returning a complete document — all without a human in the loop.

> With `LLM_PROVIDER=groq` or `ollama`, the same two requests produce the same structure with genuinely fluent, specific prose instead of the Mock provider's templated placeholders — swap the provider, nothing else changes.

---

## 🖼️ Sample Output

Generated `.docx` samples for both demonstration cases (from `demo.py`) are saved to `demo_output/` after a live run:

- `demo_output/1_standard_business_request.docx`
- `demo_output/2_complex_ambiguous_request.docx`

Each document includes a cover page, an auto-updating Word Table of Contents field (right-click → *Update Field* on first open — standard Word behavior), styled headings, shaded-header tables for tabular sections, and a header/footer with page numbers.

---

## 🚀 Future Improvements

- **Persistent storage** — swap `storage.py`'s in-memory dict for Redis/Postgres; it already sits behind a narrow two-function (`save`/`get`) interface so nothing else would need to change.
- **RAG grounding** — ground section drafting in a real knowledge base (past proposals, company policy) via a vector store instead of LLM-only generation.
- **Streaming responses** — stream the task list to the client as each section is planned, rather than waiting for the full pipeline to finish.
- **Conversation memory** — a follow-up `PATCH` endpoint for multi-turn refinement (e.g. "make section 3 shorter"), using the existing `request_id`-keyed storage.
- **Horizontal scaling** — split planner/executor/reflection into separate services communicating over a queue if section drafting needs independent scaling.

---

## 📄 License

MIT
