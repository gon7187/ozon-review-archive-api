# Ozon Multi-Agent API Worker

**Status:** approved 2026-08-25

## Goal

Turn the working browser parser into a local, authenticated FastAPI worker that
returns a durable, structured JSON archive for one Ozon product per job and a
compact review view for the multi-agent system.

## Scope

- Accept an Ozon URL, an article number, or both when they identify the same
  product.
- Use the existing Playwright browser path and DOM/JSON-LD extraction only;
  do not depend on Ozon's official seller API or add internal Ozon endpoints.
- Persist one archive at `output/<article>.json`.
- Run one browser job at a time in an in-process queue.
- Expose an authenticated `/api/v1` job API with OpenAPI documentation.
- Keep the current GUI-compatible text-fetch function as a compatibility
  wrapper.

## JSON contract

Each successful or partial result has this envelope:

```json
{
  "schema_version": "1.0",
  "job": {
    "job_id": "...",
    "attempt": 1,
    "proxy_rotated": false
  },
  "product": {
    "requested_url": "...",
    "source_url": "...",
    "article": "138342427",
    "name": "...",
    "category_path": null,
    "brand": null,
    "seller": null,
    "price": null,
    "rating": null,
    "reviews_count": null,
    "fetched_at": "2026-08-25T00:00:00+00:00"
  },
  "reviews": [],
  "analysis_reviews": [],
  "warnings": []
}
```

`reviews` contains the maximum fields available from the DOM: `review_id`,
`author`, `rating`, `date`, `text`, `pros`, `cons`, `purchased`, `likes`,
`dislikes`, `photos`, and `videos`. Missing scalar fields are `null`; missing
media collections are `[]`. Reviews without an Ozon ID are retained and are
not deduplicated by text.

`analysis_reviews` contains only `text`, `pros`, `cons`, and `rating` for the
multi-agent analysis path. It is not Gemini-specific.

## API

All endpoints except `/api/v1/healthz` require
`Authorization: Bearer $API_TOKEN`.

- `POST /api/v1/jobs` creates one job. It accepts `url`, `article`,
  `max_reviews` (default 200, server maximum 5000), `timeout_seconds` (default
  600, server maximum 2800), and `fresh_profile` (default false).
- `GET /api/v1/jobs/{job_id}` returns status/progress/warnings/error.
- `GET /api/v1/jobs/{job_id}/result` returns the full JSON after
  `succeeded` or `partial`.
- `POST /api/v1/jobs/{job_id}/cancel` requests cancellation.
- `POST /api/v1/jobs/{job_id}/retry` performs at most one retry.
- `POST /api/v1/jobs/{job_id}/rotate-proxy` calls the preconfigured provider
  URL only; retry remains a separate operation.
- `GET /api/v1/healthz` returns service health without exposing secrets.

`Idempotency-Key` prevents duplicate jobs after a caller timeout. Conflicting
URL and article inputs are rejected with HTTP 400 before a browser starts.

## Lifecycle and failure behavior

Jobs use `queued`, `running`, `waiting_for_captcha`, `succeeded`, `partial`,
`failed`, and `cancelled`. A product with reviews can be `succeeded` even if
optional metadata is `null`. A clean zero-review result is `partial`; browser,
timeout, validation, and provider failures are `failed` with an explicit
error. Captcha is surfaced as `waiting_for_captcha` while the visible browser
waits for manual resolution. A running job is bounded by its configured
timeout.

## Runtime and security

- `API_TOKEN`, `DEFAULT_MAX_REVIEWS`, `MAX_MAX_REVIEWS`,
  `DEFAULT_TIMEOUT_SECONDS`, `MAX_TIMEOUT_SECONDS`, `OZON_PROFILE_DIR`,
  `OZON_PROXY_URL`, `PROXY_ROTATE_URL`, and optional
  `PROXY_ROTATE_TOKEN` come from environment/configuration.
- Proxy credentials and provider response bodies never enter job JSON or logs.
- The service binds to localhost by default. It uses one persistent Chrome
  profile; `fresh_profile` is explicit and exceptional.
- No database, Redis, S3, public listener, or automatic infinite retry is part
  of this version.

## Verification and documentation

The implementation must include offline parser tests, API contract tests, and
one live smoke run against a public Ozon card. Documentation lives in both the
README quick start and `docs/API.md`, with endpoint tables, state/error
semantics, JSON examples, curl, and Python examples.
