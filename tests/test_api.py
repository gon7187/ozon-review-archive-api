from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api import create_app
from app.job_manager import JobManager


def wait_for_status(
    client: TestClient, token: str, job_id: str, expected: str
) -> dict[str, Any]:
    for _ in range(100):
        response = client.get(
            f"/api/v1/jobs/{job_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        body = response.json()
        if body["status"] == expected:
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach {expected}")


def archive_for(article: str) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "job": {},
        "product": {"article": article, "name": "Товар"},
        "reviews": [{"review_id": "r1", "text": "Хороший товар"}],
        "analysis_reviews": [
            {"text": "Хороший товар", "pros": None, "cons": None, "rating": None}
        ],
        "warnings": [],
    }


def test_health_is_public_and_jobs_require_bearer(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    client = TestClient(
        create_app(JobManager(fetcher=lambda *args, **kwargs: (None, "unused")))
    )

    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/api/v1/healthz").json() == {"status": "ok"}
    assert client.post("/api/v1/jobs", json={"article": "123456"}).status_code == 401


def test_job_is_async_idempotent_and_result_is_saved(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("API_TOKEN", "test-token")

    def fetcher(source: str, **kwargs: Any) -> tuple[dict[str, Any], None]:
        return archive_for("123456"), None

    client = TestClient(create_app(JobManager(fetcher=fetcher, output_dir=tmp_path)))
    headers = {"Authorization": "Bearer test-token", "Idempotency-Key": "one"}
    payload = {"url": "https://www.ozon.ru/product/test-123456/", "max_reviews": 5}

    first = client.post("/api/v1/jobs", json=payload, headers=headers)
    second = client.post("/api/v1/jobs", json=payload, headers=headers)

    assert first.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    job = wait_for_status(client, "test-token", first.json()["id"], "succeeded")
    result = client.get(
        f"/api/v1/jobs/{job['id']}/result",
        headers={"Authorization": "Bearer test-token"},
    )
    assert result.status_code == 200
    assert result.json()["product"]["article"] == "123456"
    assert (tmp_path / "123456.json").exists()


def test_conflicting_source_is_rejected(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    client = TestClient(
        create_app(JobManager(fetcher=lambda *args, **kwargs: (None, "unused")))
    )

    response = client.post(
        "/api/v1/jobs",
        json={"url": "https://www.ozon.ru/product/test-123456/", "article": "654321"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 400


def test_non_ozon_source_is_rejected_before_queue(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    client = TestClient(
        create_app(JobManager(fetcher=lambda *args, **kwargs: (None, "unused")))
    )

    response = client.post(
        "/api/v1/jobs",
        json={"url": "https://example.com/product/test-123456/"},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 400


def test_failed_job_can_rotate_proxy_and_retry_once(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("API_TOKEN", "test-token")
    calls = 0
    rotations = 0

    def fetcher(source: str, **kwargs: Any) -> tuple[dict[str, Any] | None, str | None]:
        nonlocal calls
        calls += 1
        return (None, "temporary") if calls == 1 else (archive_for("123456"), None)

    def rotate() -> None:
        nonlocal rotations
        rotations += 1

    client = TestClient(
        create_app(
            JobManager(fetcher=fetcher, proxy_rotator=rotate, output_dir=tmp_path)
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    created = client.post(
        "/api/v1/jobs", json={"article": "123456"}, headers=headers
    ).json()
    wait_for_status(client, "test-token", created["id"], "failed")

    rotated = client.post(f"/api/v1/jobs/{created['id']}/rotate-proxy", headers=headers)
    assert rotated.status_code == 200
    assert rotations == 1
    assert (
        client.post(f"/api/v1/jobs/{created['id']}/retry", headers=headers).status_code
        == 200
    )
    wait_for_status(client, "test-token", created["id"], "succeeded")
    assert (
        client.post(f"/api/v1/jobs/{created['id']}/retry", headers=headers).status_code
        == 409
    )


def test_cancel_stops_a_running_job(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("API_TOKEN", "test-token")
    started = threading.Event()

    def fetcher(source: str, **kwargs: Any) -> tuple[None, str]:
        started.set()
        while not kwargs["should_cancel"]():
            time.sleep(0.005)
        return None, "cancelled"

    client = TestClient(create_app(JobManager(fetcher=fetcher, output_dir=tmp_path)))
    headers = {"Authorization": "Bearer test-token"}
    created = client.post(
        "/api/v1/jobs", json={"article": "123456"}, headers=headers
    ).json()
    assert started.wait(1)

    cancelled = client.post(f"/api/v1/jobs/{created['id']}/cancel", headers=headers)

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_captcha_can_rotate_then_retry(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("API_TOKEN", "test-token")
    calls = 0
    rotations = 0

    def fetcher(source: str, **kwargs: Any) -> tuple[dict[str, Any] | None, str | None]:
        nonlocal calls
        calls += 1
        if calls == 1:
            kwargs["on_captcha"]()
            while not kwargs["should_cancel"]():
                time.sleep(0.005)
            return None, "cancelled"
        return archive_for("123456"), None

    def rotate() -> None:
        nonlocal rotations
        rotations += 1

    client = TestClient(
        create_app(
            JobManager(fetcher=fetcher, proxy_rotator=rotate, output_dir=tmp_path)
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    created = client.post(
        "/api/v1/jobs", json={"article": "123456"}, headers=headers
    ).json()
    wait_for_status(client, "test-token", created["id"], "waiting_for_captcha")

    assert (
        client.post(
            f"/api/v1/jobs/{created['id']}/rotate-proxy", headers=headers
        ).status_code
        == 200
    )
    retried = client.post(f"/api/v1/jobs/{created['id']}/retry", headers=headers)

    assert retried.status_code == 200
    assert rotations == 1
    wait_for_status(client, "test-token", created["id"], "succeeded")
    assert calls == 2


def test_proxy_rotation_rejects_concurrent_call(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("API_TOKEN", "test-token")
    captcha_started = threading.Event()
    rotation_started = threading.Event()
    release_rotation = threading.Event()

    def fetcher(source: str, **kwargs: Any) -> tuple[None, str]:
        captcha_started.set()
        kwargs["on_captcha"]()
        while not kwargs["should_cancel"]():
            time.sleep(0.005)
        return None, "cancelled"

    def rotate() -> None:
        rotation_started.set()
        release_rotation.wait(1)

    client = TestClient(
        create_app(
            JobManager(fetcher=fetcher, proxy_rotator=rotate, output_dir=tmp_path)
        )
    )
    headers = {"Authorization": "Bearer test-token"}
    created = client.post(
        "/api/v1/jobs", json={"article": "123456"}, headers=headers
    ).json()
    assert captcha_started.wait(1)
    wait_for_status(client, "test-token", created["id"], "waiting_for_captcha")

    first_result: dict[str, Any] = {}

    def call_rotate() -> None:
        first_result["response"] = client.post(
            f"/api/v1/jobs/{created['id']}/rotate-proxy", headers=headers
        )

    thread = threading.Thread(target=call_rotate)
    thread.start()
    assert rotation_started.wait(1)
    second = client.post(f"/api/v1/jobs/{created['id']}/rotate-proxy", headers=headers)
    release_rotation.set()
    thread.join(1)

    assert second.status_code == 409
    assert first_result["response"].status_code == 200
