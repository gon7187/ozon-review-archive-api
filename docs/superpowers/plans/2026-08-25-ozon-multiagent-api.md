# Ozon Multi-Agent API Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local FastAPI job worker that archives structured Ozon reviews and exposes a documented multi-agent API without breaking the existing GUI text interface.

**Architecture:** Keep browser extraction in `app/ozon_parser.py`; add a small in-process `JobManager` with one worker and an API adapter in `app/api.py`. The parser writes `output/<article>.json`, while the API returns the same envelope and a compact `analysis_reviews` projection.

**Tech Stack:** Python 3.11+, Playwright, FastAPI, Uvicorn, Pydantic, pytest, standard-library queue/threading/urllib.

## Global Constraints

- One browser job at a time; no database, Redis, S3, or public listener.
- `max_reviews` defaults to 200 and cannot exceed 5000.
- `timeout_seconds` defaults to 600 and cannot exceed 2800.
- Missing scalar data is `null`; missing media lists are `[]`; never invent values.
- `API_TOKEN` and proxy configuration are environment-only and never logged or serialized.
- Preserve `fetch_product_data_and_reviews()` for the existing GUI.

---

### Task 1: Structured product and review extraction

**Files:**
- Modify: `app/ozon_parser.py`
- Create: `tests/test_ozon_parser.py`

**Interfaces:**
- Produce `fetch_product_archive_and_reviews(source, reviews_limit=200, timeout_seconds=600, fresh_profile=False, on_captcha=None, should_cancel=None) -> tuple[dict | None, str | None]`.
- Preserve `fetch_product_data_and_reviews(source, reviews_limit=200) -> tuple[list[str] | None, str | None, str | None]` as a compatibility wrapper.

- [ ] **Step 1: Write failing pure extraction tests**

```python
def test_jsonld_product_fields_are_normalized():
    result = parse_product_jsonld(['{"@type":"Product","brand":{"name":"Fairy"},"category":"Дом","offers":{"price":"199"}}'])
    assert result == {"brand": "Fairy", "category_path": ["Дом"], "price": "199"}

def test_review_records_keep_id_and_analysis_projection():
    record = make_review_record("r-1", "Полезный текст", rating=5)
    assert record["review_id"] == "r-1"
    assert project_for_analysis([record]) == [{"text": "Полезный текст", "pros": None, "cons": None, "rating": 5}]

def test_compatibility_wrapper_returns_texts_from_archive(monkeypatch):
    monkeypatch.setattr("app.ozon_parser.fetch_product_archive_and_reviews", lambda *a, **k: ({"product":{"name":"X"}, "reviews":[{"text":"Текст"}]}, None))
    assert fetch_product_data_and_reviews("123456") == (["Текст"], "X", None)
```

- [ ] **Step 2: Run the focused tests and confirm the expected missing-symbol failures**

Run: `pytest -q tests/test_ozon_parser.py`

Expected: FAIL because the structured extraction functions do not exist yet.

- [ ] **Step 3: Implement the smallest structured extraction path**

Add pure JSON-LD normalization, review-record construction, analysis projection,
product metadata collection, JSON persistence, timeout/captcha callbacks, and
the compatibility wrapper. Keep the existing selectors and scrolling loop as
fallbacks; add best-effort selectors only for fields requested by the contract.

- [ ] **Step 4: Run the focused tests and then the parser tests again**

Run: `pytest -q tests/test_ozon_parser.py`

Expected: all focused tests pass with no warnings.

- [ ] **Step 5: Commit the parser slice**

Run: `git add app/ozon_parser.py tests/test_ozon_parser.py && git commit -m "feat: return structured Ozon review archives"`

### Task 2: Job manager, proxy rotation, and API contract

**Files:**
- Create: `app/job_manager.py`
- Create: `app/api.py`
- Create: `app/proxy.py`
- Create: `tests/test_api.py`

**Interfaces:**
- `JobManager.submit(request, idempotency_key=None) -> Job`.
- `JobManager.status(job_id) -> Job`.
- `JobManager.result(job_id) -> dict`.
- `JobManager.cancel(job_id)`, `retry(job_id)`, and `rotate_proxy(job_id)`.
- FastAPI routes under `/api/v1/jobs` and `/api/v1/healthz`.

- [ ] **Step 1: Write failing API contract tests**

Cover authenticated creation, URL/article conflict `400`, idempotency reuse,
queued status, result gating, cancel, one retry, proxy rotation configuration,
and health without auth. Use a fake synchronous fetcher injected into
`JobManager`, not a browser mock hidden behind implementation details.

- [ ] **Step 2: Run the API tests and confirm RED**

Run: `pytest -q tests/test_api.py`

Expected: FAIL because `app.api` and `app.job_manager` do not exist.

- [ ] **Step 3: Implement configuration validation and proxy rotation**

Read environment defaults once, validate `1 <= max_reviews <= 5000` and
`1 <= timeout_seconds <= 2800`, call only the configured `PROXY_ROTATE_URL`,
and return provider failures without exposing response bodies.

- [ ] **Step 4: Implement the one-worker job manager**

Use a queue and one daemon worker. Maintain the approved lifecycle, attempt
counter, timestamps, progress count, warnings, error, idempotency map, and
one retry limit. Pass captcha/cancel callbacks into the parser and persist
completed/partial envelopes to `output/<article>.json`.

- [ ] **Step 5: Implement FastAPI routes and auth**

Use `Authorization: Bearer $API_TOKEN`, `Idempotency-Key`, Pydantic request
validation, HTTP 400/401/404/409/422/502 errors, and separate status/result
responses. Keep health response non-sensitive.

- [ ] **Step 6: Run the API tests and commit**

Run: `pytest -q tests/test_api.py`

Expected: all API tests pass.

Commit: `git add app/api.py app/job_manager.py app/proxy.py tests/test_api.py && git commit -m "feat: expose asynchronous Ozon job API"`

### Task 3: Dependencies and developer documentation

**Files:**
- Modify: `requirements.txt`
- Create: `requirements-dev.txt`
- Modify: `README.md`
- Create: `docs/API.md`

- [ ] **Step 1: Add runtime and test dependencies**

Add FastAPI and Uvicorn to `requirements.txt`; add pytest and HTTPX to
`requirements-dev.txt` without putting test-only packages in runtime installs.

- [ ] **Step 2: Document the API**

Document environment variables, startup with Uvicorn, Bearer auth, every
endpoint, request/response examples, lifecycle, CAPTCHA, retry/rotate flow,
limits, JSON retention, and curl/Python calls. Keep the README as a concise
quick-start pointing to `docs/API.md`.

- [ ] **Step 3: Verify documentation examples and commit**

Run: `python -m compileall -q app main.py` and `git diff --check`.

Commit: `git add requirements.txt requirements-dev.txt README.md docs/API.md && git commit -m "docs: document Ozon multi-agent worker API"`

### Task 4: Full verification and handoff

**Files:**
- Modify only files required by failing verification.

- [ ] **Step 1: Run all offline tests**

Run: `pytest -q`.

- [ ] **Step 2: Run repository self-checks on changed Python files**

Run: `ruff check --fix app/api.py app/job_manager.py app/ozon_parser.py app/proxy.py tests/test_api.py tests/test_ozon_parser.py`; then `ruff format` on the same files; then `pyright` on changed Python files.

- [ ] **Step 3: Run live smoke verification**

Start the API with a test `API_TOKEN`, submit article `138342427` with
`max_reviews=5`, poll status, and verify the result contains `product.article`,
`reviews`, `analysis_reviews`, and a JSON file under `output/`.

- [ ] **Step 4: Review the final diff and record the result**

Run `git diff origin/main...HEAD`, `git status --short --branch`, and the full
test command again before integration.
