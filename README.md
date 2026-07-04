# Autonomous Document-Generation Agent

A FastAPI service that takes a natural-language request, autonomously plans and
executes its own task list, self-checks its own output, and returns a polished
`.docx`. See `../autonomous_agent_build_guide.md` for the full step-by-step
build guide and architecture rationale.

## Status: Steps 1–11 complete (full pipeline wired end-to-end)

| Step | What | Status |
|---|---|---|
| 1 | Project setup (venv, dependencies, package skeleton) | ✅ done |
| 2 | Configuration layer (`app/config.py`) | ✅ done |
| 3 | Data contracts & request guardrails (`app/schemas.py`) | ✅ done |
| 4 | Document type templates (`app/templates.py`) | ✅ done |
| 5 | LLM abstraction layer (Groq / Ollama / Mock) (`app/llm_client.py`) | ✅ done |
| 6 | Autonomous planner (`app/planner.py`) | ✅ done |
| 7 | Executor (concurrent section drafting) (`app/executor.py`) | ✅ done |
| 8 | Reflection / self-check loop (`app/reflection.py`) | ✅ done |
| 9 | `.docx` rendering (`app/doc_generator.py`) | ✅ done |
| 10 | Storage (`app/storage.py`) | ✅ done |
| 11 | FastAPI app & routes (`app/main.py`) | ✅ done |
| 12 | Automated tests (full pipeline) | ✅ done |
| 13 | Demo script (`demo.py`) | ✅ done |

`POST /agent` now runs the complete pipeline:
**Request → Planner → Executor → Reflection (review only) → targeted revise
of flagged sections → DOCX → Response**, and returns a `download_url` for
the generated `.docx`.

## Project layout (so far)

```
agent_project/
├── app/
│   ├── __init__.py
│   ├── config.py          # env-based settings
│   ├── schemas.py         # Pydantic request/response/plan contracts
│   ├── templates.py       # reference section structures per document type
│   ├── llm_client.py      # Groq / Ollama / Mock behind one interface
│   ├── planner.py         # autonomous plan generation
│   ├── executor.py        # concurrent section drafting + targeted revision
│   ├── reflection.py      # review-only self-check loop (reuses executor.revise_section)
│   ├── doc_generator.py   # python-docx rendering
│   ├── storage.py         # in-memory request_id -> file/plan registry
│   └── main.py            # FastAPI app & routes
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_schemas.py
│   ├── test_templates.py
│   ├── test_llm_client.py
│   ├── test_planner.py
│   ├── test_executor.py
│   ├── test_reflection.py
│   ├── test_doc_generator.py
│   ├── test_storage.py
│   └── test_main.py       # endpoint tests + the two required assignment cases
├── demo.py                # live run of the two required test cases against a running server
├── demo_output/           # .docx files saved by demo.py
├── generated_docs/        # output dir used by the live API, auto-created by config.py
├── requirements.txt
├── .env.example
└── README.md
```

## File overview

- **`app/config.py`** — every tunable setting (LLM provider, model names,
  retry counts, timeouts, guardrail limits) read once from environment
  variables via `python-dotenv`. Centralising these means swapping providers
  or tightening a guardrail is an env-var change, not a code change.
- **`app/schemas.py`** — Pydantic v2 models forming typed contracts between
  every future pipeline stage (planner → executor → reflection → renderer),
  plus the `AgentRequest` guardrail that rejects requests that are blank,
  too short (< 8 chars), or too long (> 4000 chars) with a clean `422`
  before any LLM call would be made.
- **`.env.example`** — copy to `.env` and fill in to configure a real LLM
  provider (Groq or Ollama); defaults to the offline `mock` provider.
- **`requirements.txt`** — pinned dependencies. Note: `pydantic` is pinned
  to `2.13.4` rather than the guide's `2.9.2` — this machine runs Python
  3.14, and `pydantic-core 2.23.4` (what `pydantic==2.9.2` requires) has no
  prebuilt Windows wheel for `cp314`, forcing a from-source Rust build that
  fails without the MSVC linker. `2.13.4` is the latest release with a
  precompiled `cp314` wheel; the API surface used here (`BaseModel`, `Field`,
  `field_validator`) is unchanged since Pydantic v2.0.
- **`tests/test_config.py`** — verifies defaults load correctly with no env
  vars set, that env vars override those defaults, and that `OUTPUT_DIR` is
  created on import.
- **`tests/test_schemas.py`** — verifies the `AgentRequest` guardrail
  (accepts valid/boundary-length text, strips whitespace, rejects
  blank/too-short/too-long input) and that `Plan`, `SectionContent`,
  `SectionFeedback`, `ReflectionResult`, and `AgentResponse` build and
  round-trip as expected.
- **`app/templates.py`** — reference section structures for the 7 supported
  business-document types (proposal, meeting minutes, project plan, business
  report, technical design, SOP, product spec). Each section is
  `(id, title, table_columns_or_None)`. Serves two purposes: few-shot
  grounding shown to the planner prompt, and `default_plan_dict()`, the
  deterministic fallback plan used if the LLM's plan output can't be parsed
  at all. `classify_keyword_fallback()` is a cheap keyword heuristic used by
  the Mock LLM and by the deterministic fallback to pick a document type
  without needing a model call.
- **`app/llm_client.py`** — one `LLMClient` abstract interface with three
  implementations: `GroqLLM` (primary — free-tier hosted, OpenAI-compatible
  REST API), `OllamaLLM` (optional — fully local REST API), and `MockLLM`
  (deterministic offline stub used by default and by tests, so nothing here
  requires a network call or API key). `LLMClient.generate()` wraps every
  provider call with exponential-backoff retries (`LLM_MAX_RETRIES` from
  config) and raises `LLMError` only once every attempt has failed.
  `get_llm_client()` is the factory: it builds whatever `LLM_PROVIDER`
  points to, health-checks it once, and transparently falls back to
  `MockLLM` if the provider is unreachable, misconfigured, or unrecognised —
  so a missing `GROQ_API_KEY` or a local Ollama server that isn't running
  degrades gracefully instead of crashing the app.
- **`app/planner.py`** — `create_plan()` turns a free-text request into a
  validated `Plan` (document type, title, audience, assumptions, ordered
  sections) using `PLANNER_SYSTEM_PROMPT`, which explicitly instructs the
  model to state an assumption instead of asking a follow-up question. Three
  tiers of resilience against free/small models that don't reliably return
  clean JSON: (1) parse the first reply directly, (2) if that fails, send
  the exact parse error back to the model once for self-correction, (3) if
  it still fails, fall back to `templates.default_plan_dict()` so a
  formatting failure never surfaces as a crash.
- **`app/executor.py`** — `execute_plan()` drafts every section in the plan
  concurrently via `asyncio.gather` (each LLM call moved off the event loop
  with `asyncio.to_thread`, since the underlying `requests` calls are
  synchronous). Every section prompt carries the same shared plan context
  (title, audience, assumptions) so independently-drafted sections stay
  thematically consistent despite never reading each other's text — the
  speed/coherence tradeoff called out in the guide. `_parse_section_output()`
  parses table sections as a JSON array of rows and degrades to a
  single-row placeholder if a model's table output isn't valid JSON, rather
  than failing the whole section. `revise_section()` re-drafts one flagged
  section with the specific issue in-prompt — reused directly by the
  reflection loop below (not duplicated).
- **`app/reflection.py`** — THE MANDATORY ENGINEERING IMPROVEMENT.
  `run_reflection_loop()` is deliberately **review-only**: it prompts an LLM
  acting as a quality reviewer to check every section against the original
  request, and for anything flagged, delegates the rewrite to
  `executor.revise_section()` — the exact same function the executor already
  exposes. This module contains no drafting/generation logic of its own, so
  there's a single place that knows how to turn `(plan, section, issue)`
  into new content. Bounded to `MAX_REFLECTION_ROUNDS` (default 2) so a
  stubborn model can't loop forever; a reviewer that can't be reached just
  skips its round (logged as `"skipped (reviewer unavailable)"`) rather than
  failing the request — a broken reviewer should never block shipping an
  already-valid document. Every round is logged into `reflection_log`,
  returned in the API response and inspectable via `GET /agent/plan/{id}`.
- **`app/doc_generator.py`** — `build_docx()` renders the final `.docx`:
  cover page, a real Word `TOC` field (shows placeholder text until opened
  in Word, which prompts to update fields — standard Word behavior, not a
  bug), styled headings, shaded-header Word tables for tabular sections, and
  a header/footer with a `PAGE` field. Revised sections get a small
  "*(refined by the agent's self-check pass)*" note. Uses direct
  `docx.oxml` manipulation for the two field codes (`TOC`, `PAGE`) that
  `python-docx`'s high-level API doesn't wrap natively.
- **`app/storage.py`** — a plain `dict` behind a two-function
  `save()`/`get()` interface mapping `request_id -> {path, plan,
  reflection_log}`. In-memory is intentional for this single-process demo
  service; the narrow interface means swapping in Redis/Postgres later
  wouldn't touch `main.py`.
- **`app/main.py`** — wires `create_plan` → `execute_plan` →
  `run_reflection_loop` → `build_docx` into `POST /agent`, plus
  `GET /agent/download/{request_id}` (binary `.docx` download, kept separate
  from the JSON response so the response body stays small and log-friendly),
  `GET /agent/plan/{request_id}` (transparency — inspect the exact plan +
  reflection log behind any generated document), and `GET /health`.
  Planning/execution failures that exhaust retries return a clean `502`;
  rendering failures return `500`. Reflection failures never surface as HTTP
  errors — they're already contained inside `reflection.py`.
- **`demo.py`** — drives the two required assignment test cases (one
  standard business request, one complex/ambiguous request) against a
  *running* server and prints the agent's self-generated task list,
  assumptions, and reflection log — the human-watchable counterpart to the
  assertion-based versions of the same two cases in `tests/test_main.py`.

## Setup

```bash
cd agent_project
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash; use .venv\Scripts\activate.bat for cmd.exe
pip install -r requirements.txt
cp .env.example .env            # optional — defaults to LLM_PROVIDER=mock
```

## Running the tests

```bash
python -m pytest -v
```

Current result: **84 passed**.

All tests run against fakes/mocks (`MockLLM`, and hand-written `LLMClient`
subclasses for retry/failure scenarios) — no network calls are made, no
`GROQ_API_KEY` or local Ollama server is required. `tests/test_main.py`
includes the two required assignment test cases (standard + complex/
ambiguous request), run through the full in-process pipeline via FastAPI's
`TestClient`; pass `-s` to see the printed task list/assumptions/reflection
log for each. A shared `no_real_llm_sleep` autouse fixture in
`tests/conftest.py` patches out retry backoff delays for every test in the
suite.

## Running the live demo

```bash
uvicorn app.main:app --reload      # terminal 1 (defaults to LLM_PROVIDER=mock)
python demo.py                     # terminal 2
```

`demo.py` posts the same two required test cases to the running server and
saves each generated `.docx` to `demo_output/`. Verified output for both
cases (mock provider): the agent independently picks `project_plan` for the
standard request and `sop` for the ambiguous one (no document type, budget,
or deadline given), states explicit assumptions instead of asking a
follow-up question, and its self-check flags and revises several thin
first-draft sections in round 1 before passing clean in round 2 — matching
the guide's own captured reference output.

## Final review

A full pass over every file for dead code, duplication, unused imports,
naming, type hints, hardcoded values, error handling, and PEP 8 turned up
two real bugs, one piece of dead/misleading code, and several smaller
cleanups — all fixed without changing the architecture:

- **Revision failures could crash a request.** `reflection.py` wrapped the
  *review* LLM call in try/except but not the *revision* calls it triggers
  for flagged sections — a transient failure there would propagate as an
  unhandled 500, contradicting the module's own "never blocks shipping"
  design. Fixed: a failed revision now keeps that section's previous draft
  and is noted in `reflection_log` instead of raising.
- **A schema-invalid LLM plan could crash a request.** `planner.py`'s
  three-tier resilience covered unparseable JSON, but a reply that parsed
  fine yet was missing a field `Plan` requires (e.g. a section without a
  `"title"`) raised an uncaught `pydantic.ValidationError`. Fixed: a fourth
  tier catches that case and falls back to the same deterministic template.
- **Dead/misleading code removed.** `ReflectionResult` in `schemas.py` was
  never instantiated anywhere in the real pipeline, and its documented
  shape didn't even match the `reflection_log` dicts actually produced at
  runtime — removed along with its test.
- **Hardcoded guardrail values.** `AgentRequest`'s length validator
  hardcoded `8`/`4000` instead of reading `config.MIN_REQUEST_LENGTH`/
  `MAX_REQUEST_LENGTH`, which existed for exactly this purpose but were
  dead — changing the env var did nothing. Now wired through.
- **Smaller cleanups:** deduplicated the accent-color hex string and the
  `get_llm_client()` health-check literals; added missing return type hints
  across `executor.py`/`reflection.py`/`main.py`/`llm_client.py`; split
  `doc_generator.py`'s semicolon-chained statements onto separate lines
  (PEP 8 E702); added OpenAPI `summary` text to every route; centralized a
  `time.sleep` test patch that had been copy-pasted across four test files
  into one `tests/conftest.py` fixture.

Two regression tests were added for the two real bugs
(`test_reflection_keeps_previous_draft_when_revision_fails`,
`test_create_plan_falls_back_to_template_when_json_is_valid_but_fails_plan_validation`).
All 84 tests pass and the two required assignment cases were re-verified
live against the running server with identical output to before the review.
