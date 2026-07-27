from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse


class Marketplace(StrEnum):
    WILDBERRIES = "Wildberries"
    OZON = "Ozon"


@dataclass(frozen=True)
class ProductReviews:
    marketplace: Marketplace
    product_id: str
    product_name: str
    reviews: list[str]


def detect_marketplace(value: str) -> Marketplace:
    candidate = value.strip()
    host = urlparse(candidate if "://" in candidate else f"https://{candidate}").hostname or ""
    host = host.lower().removeprefix("www.")

    if any(host == domain or host.endswith(f".{domain}") for domain in ("ozon.ru", "ozon.by")):
        return Marketplace.OZON
    if host == "wildberries.ru" or host.endswith(".wildberries.ru"):
        return Marketplace.WILDBERRIES
    if candidate.isdigit():
        raise ValueError("Для артикула без ссылки выберите маркетплейс.")
    raise ValueError("Поддерживаются ссылки на ozon.ru, ozon.by и wildberries.ru.")
