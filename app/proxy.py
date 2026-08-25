from __future__ import annotations

import os
from urllib.request import Request, urlopen


def rotate_proxy() -> None:
    endpoint = os.getenv("PROXY_ROTATE_URL")
    if not endpoint:
        raise RuntimeError("PROXY_ROTATE_URL не настроен.")

    method = os.getenv("PROXY_ROTATE_METHOD", "POST").upper()
    headers = {}
    token = os.getenv("PROXY_ROTATE_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(endpoint, headers=headers, method=method)
    try:
        with urlopen(request, timeout=20) as response:
            response_status = response.status
    except Exception:  # noqa: BLE001 - не выдаём endpoint или токен наружу.
        raise RuntimeError("Не удалось вызвать сервис ротации прокси.") from None
    if response_status >= 400:
        raise RuntimeError("Сервис ротации прокси вернул ошибку.")
