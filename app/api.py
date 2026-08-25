from __future__ import annotations

import os
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.job_manager import JobManager
from app.ozon_parser import (
    DEFAULT_REVIEWS_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_REVIEWS_LIMIT,
    MAX_TIMEOUT_SECONDS,
    get_product_id_from_url,
)


class JobRequest(BaseModel):
    url: str | None = None
    article: str | None = None
    max_reviews: int = Field(DEFAULT_REVIEWS_LIMIT, ge=1, le=MAX_REVIEWS_LIMIT)
    timeout_seconds: int = Field(DEFAULT_TIMEOUT_SECONDS, ge=1, le=MAX_TIMEOUT_SECONDS)
    fresh_profile: bool = False


bearer = HTTPBearer(auto_error=False)


def _require_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> None:
    expected = os.getenv("API_TOKEN")
    if (
        not expected
        or credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(credentials.credentials, expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Нужен корректный Bearer API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _normalize_source(request: JobRequest) -> tuple[str | None, str]:
    url = request.url.strip() if request.url else None
    article_from_url = get_product_id_from_url(url) if url else None
    article = request.article.strip() if request.article else None
    if url and not article_from_url:
        raise _bad_request("В url не найден артикул Ozon.")
    if article and not article.isdigit():
        raise _bad_request("article должен содержать только цифры.")
    if url and article and article != article_from_url:
        raise _bad_request("url и article указывают на разные товары.")
    normalized_article = article or article_from_url
    if not normalized_article:
        raise _bad_request("Передайте url или article.")
    return url, normalized_article


def _manager_error(error: Exception) -> HTTPException:
    if isinstance(error, KeyError):
        return HTTPException(status_code=404, detail="Задача не найдена.")
    if isinstance(error, RuntimeError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=500, detail="Ошибка менеджера задач.")


def create_app(manager: JobManager | None = None) -> FastAPI:
    jobs = manager or JobManager()
    application = FastAPI(
        title="Ozon Review Archive API",
        version="1.0.0",
        description="Асинхронная выгрузка структурированных отзывов Ozon для мультиагентной системы.",
    )

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    protected = [Depends(_require_token)]

    @application.post("/api/v1/jobs", status_code=202, dependencies=protected)
    def create_job(
        request: JobRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict:
        url, article = _normalize_source(request)
        return jobs.submit(
            url=url,
            article=article,
            max_reviews=request.max_reviews,
            timeout_seconds=request.timeout_seconds,
            fresh_profile=request.fresh_profile,
            idempotency_key=idempotency_key,
        )

    @application.get("/api/v1/jobs/{job_id}", dependencies=protected)
    def get_job(job_id: str) -> dict:
        try:
            return jobs.get(job_id)
        except Exception as exc:
            raise _manager_error(exc) from exc

    @application.get("/api/v1/jobs/{job_id}/result", dependencies=protected)
    def get_result(job_id: str) -> dict:
        try:
            return jobs.result(job_id)
        except Exception as exc:
            raise _manager_error(exc) from exc

    @application.post("/api/v1/jobs/{job_id}/cancel", dependencies=protected)
    def cancel_job(job_id: str) -> dict:
        try:
            return jobs.cancel(job_id)
        except Exception as exc:
            raise _manager_error(exc) from exc

    @application.post("/api/v1/jobs/{job_id}/retry", dependencies=protected)
    def retry_job(job_id: str) -> dict:
        try:
            return jobs.retry(job_id)
        except Exception as exc:
            raise _manager_error(exc) from exc

    @application.post("/api/v1/jobs/{job_id}/rotate-proxy", dependencies=protected)
    def rotate_proxy(job_id: str) -> dict:
        try:
            return jobs.rotate_proxy_for_job(job_id)
        except Exception as exc:
            raise _manager_error(exc) from exc

    return application


app = create_app()
