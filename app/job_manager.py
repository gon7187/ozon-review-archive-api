from __future__ import annotations

import queue
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.ozon_parser import (
    fetch_product_archive_and_reviews,
    sanitize_error,
    save_archive,
)
from app.proxy import rotate_proxy

JobFetcher = Callable[..., tuple[dict[str, Any] | None, str | None]]
JobProxyRotator = Callable[[], None]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    url: str | None
    article: str
    max_reviews: int
    timeout_seconds: int
    fresh_profile: bool
    status: str = "queued"
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    reviews_collected: int = 0
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    attempt: int = 0
    retry_count: int = 0
    proxy_rotated: bool = False
    archive: dict[str, Any] | None = field(default=None, repr=False)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)


class JobManager:
    def __init__(
        self,
        *,
        fetcher: JobFetcher = fetch_product_archive_and_reviews,
        proxy_rotator: JobProxyRotator = rotate_proxy,
        output_dir: str | Path | None = None,
    ) -> None:
        self._fetcher = fetcher
        self._proxy_rotator = proxy_rotator
        self._output_dir = output_dir
        self._jobs: dict[str, Job] = {}
        self._idempotency: dict[str, str] = {}
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.RLock()
        threading.Thread(target=self._worker, name="ozon-worker", daemon=True).start()

    def submit(
        self,
        *,
        url: str | None,
        article: str,
        max_reviews: int,
        timeout_seconds: int,
        fresh_profile: bool,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if idempotency_key and idempotency_key in self._idempotency:
                return self.snapshot(self._jobs[self._idempotency[idempotency_key]])
            job = Job(
                id=uuid.uuid4().hex,
                url=url,
                article=article,
                max_reviews=max_reviews,
                timeout_seconds=timeout_seconds,
                fresh_profile=fresh_profile,
            )
            self._jobs[job.id] = job
            if idempotency_key:
                self._idempotency[idempotency_key] = job.id
            self._queue.put(job.id)
            return self.snapshot(job)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return self.snapshot(job)

    def result(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status not in {"succeeded", "partial"} or job.archive is None:
                raise RuntimeError("Результат ещё не готов.")
            return job.archive

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._require(job_id)
            if job.status in {"succeeded", "partial", "failed", "cancelled"}:
                raise RuntimeError("Задачу уже нельзя отменить.")
            job.cancel_event.set()
            job.status = "cancelled"
            job.finished_at = _now()
            return self.snapshot(job)

    def retry(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._require(job_id)
            if job.retry_count >= 1:
                raise RuntimeError(
                    "Для задачи уже использована одна повторная попытка."
                )
            if job.status not in {"failed", "partial", "waiting_for_captcha"}:
                raise RuntimeError(
                    "Повторить можно только завершившуюся ошибкой задачу или "
                    "задачу после ротации прокси."
                )
            if job.status == "waiting_for_captcha" and not job.proxy_rotated:
                raise RuntimeError("Сначала вызовите rotate-proxy для этой задачи.")
            job.cancel_event.set()
            job.retry_count += 1
            job.status = "queued"
            job.started_at = None
            job.finished_at = None
            job.error = None
            job.warnings = []
            job.archive = None
            job.cancel_event = threading.Event()
            self._queue.put(job.id)
            return self.snapshot(job)

    def rotate_proxy_for_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._require(job_id)
            if job.status not in {"waiting_for_captcha", "failed"}:
                raise RuntimeError(
                    "Ротация прокси доступна в ожидании проверки или после ошибки."
                )
        self._proxy_rotator()
        with self._lock:
            job = self._require(job_id)
            job.proxy_rotated = True
            return self.snapshot(job)

    @staticmethod
    def snapshot(job: Job) -> dict[str, Any]:
        return {
            "id": job.id,
            "status": job.status,
            "url": job.url,
            "article": job.article,
            "max_reviews": job.max_reviews,
            "timeout_seconds": job.timeout_seconds,
            "fresh_profile": job.fresh_profile,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "reviews_collected": job.reviews_collected,
            "warnings": list(job.warnings),
            "error": job.error,
            "attempt": job.attempt,
            "retry_count": job.retry_count,
            "proxy_rotated": job.proxy_rotated,
        }

    def _require(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def _worker(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._run(job_id)
            finally:
                self._queue.task_done()

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._require(job_id)
            if job.status == "cancelled":
                return
            job.status = "running"
            job.started_at = _now()
            job.attempt += 1
            run_event = job.cancel_event

        def captcha() -> None:
            with self._lock:
                if job.status == "running":
                    job.status = "waiting_for_captcha"

        try:
            archive, error = self._fetcher(
                job.url or job.article,
                reviews_limit=job.max_reviews,
                timeout_seconds=job.timeout_seconds,
                fresh_profile=job.fresh_profile,
                on_captcha=captcha,
                should_cancel=run_event.is_set,
                output_dir=self._output_dir,
            )
        except Exception as exc:  # noqa: BLE001 - worker must turn crashes into job failures.
            archive, error = None, f"Ошибка worker: {sanitize_error(exc)}"

        with self._lock:
            if run_event.is_set():
                if job.status != "queued":
                    job.status = "cancelled"
                    job.finished_at = _now()
                return
            if archive is None:
                job.status = "failed"
                job.error = (
                    sanitize_error(error) if error else "Парсер не вернул результат."
                )
                job.finished_at = _now()
                return

            job.archive = archive
            job.reviews_collected = len(archive.get("reviews", []))
            job.warnings = list(archive.get("warnings", []))
            job.status = "succeeded" if job.reviews_collected else "partial"
            job.error = sanitize_error(error) if error else None
            job.finished_at = _now()
            archive["job"] = self.snapshot(job)
            save_archive(archive, self._output_dir)
