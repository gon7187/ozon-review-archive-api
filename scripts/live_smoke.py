from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import requests


def _json(response: requests.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError("API вернул не JSON-объект.")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Live smoke test Ozon archive API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--article", default="138342427")
    parser.add_argument("--max-reviews", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=600)
    args = parser.parse_args()

    token = os.environ.get("API_TOKEN")
    if not token:
        raise SystemExit("API_TOKEN не задан.")
    base_url = args.base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    created = _json(
        requests.post(
            f"{base_url}/api/v1/jobs",
            headers=headers,
            json={
                "article": args.article,
                "max_reviews": args.max_reviews,
                "timeout_seconds": args.timeout_seconds,
            },
            timeout=30,
        )
    )
    job_id = str(created["id"])
    deadline = time.monotonic() + args.timeout_seconds + 30

    while True:
        job = _json(
            requests.get(
                f"{base_url}/api/v1/jobs/{job_id}", headers=headers, timeout=30
            )
        )
        if job["status"] in {"succeeded", "partial", "failed", "cancelled"}:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("Smoke-тест не дождался завершения задачи.")
        time.sleep(1)

    if job["status"] not in {"succeeded", "partial"}:
        raise RuntimeError(str(job.get("error") or job["status"]))
    archive = _json(
        requests.get(
            f"{base_url}/api/v1/jobs/{job_id}/result",
            headers=headers,
            timeout=30,
        )
    )
    assert str(archive["product"]["article"]) == args.article
    assert isinstance(archive["reviews"], list)
    assert isinstance(archive["analysis_reviews"], list)
    assert archive["job"]["job_id"] == job_id

    archive_path = Path(os.getenv("OZON_OUTPUT_DIR", "output")) / f"{args.article}.json"
    saved = json.loads(archive_path.read_text(encoding="utf-8"))
    assert str(saved["product"]["article"]) == args.article
    print(
        json.dumps(
            {
                "status": job["status"],
                "job_id": job_id,
                "article": args.article,
                "reviews": len(archive["reviews"]),
                "archive": str(archive_path),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
