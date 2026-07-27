from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

PRODUCT_ID_PATTERNS = (
    re.compile(r"/product/(?:[^/?#]*-)?(\d{6,})(?:[/ ?#]|$)", re.IGNORECASE),
    re.compile(r"/product/(\d{6,})(?:[/ ?#]|$)", re.IGNORECASE),
)


def get_product_id_from_url(value: str) -> Optional[str]:
    candidate = value.strip()
    if candidate.isdigit():
        return candidate
    for pattern in PRODUCT_ID_PATTERNS:
        match = pattern.search(candidate)
        if match:
            return match.group(1)
    return None


def _clean_review(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    start = 0
    for index, line in enumerate(lines):
        lower = line.lower()
        if lower.startswith(("цвет товара:", "размер:", "вариант:")):
            start = index + 1
        elif re.fullmatch(r"\d{1,2} [а-яё]+ 20\d{2}", lower):
            start = max(start, index + 1)

    end = len(lines)
    for index, line in enumerate(lines[start:], start=start):
        if line.lower().startswith("вам помог"):
            end = index
            break

    useful = [
        line
        for line in lines[start:end]
        if not re.fullmatch(r"\d+ комментар(?:ий|ия|иев)", line.lower())
    ]
    return " ".join(useful).strip()


def _extract_page(page, reviews_limit: int) -> tuple[str, list[str]]:
    heading = page.locator("h1").first.text_content(timeout=8_000) or ""
    title_lines = [line.strip() for line in heading.splitlines() if line.strip()]
    title = (
        title_lines[-1]
        if title_lines
        else f"Товар Ozon {get_product_id_from_url(page.url) or ''}".strip()
    )

    reviews: list[str] = []
    seen: set[str] = set()
    stable_rounds = 0

    while len(reviews) < reviews_limit and stable_rounds < 4:
        before = len(reviews)
        candidates = page.locator("[data-review-uuid]")
        if not candidates.count():
            candidates = page.locator("[data-widget='webListReviews'] > div > div")
        for index in range(min(candidates.count(), reviews_limit * 3)):
            try:
                text = _clean_review(candidates.nth(index).inner_text(timeout=2_000))
            except Exception:
                continue
            if 15 <= len(text) <= 5_000 and text not in seen:
                seen.add(text)
                reviews.append(text)
                if len(reviews) >= reviews_limit:
                    break

        stable_rounds = stable_rounds + 1 if len(reviews) == before else 0
        page.mouse.wheel(0, 5_000)
        page.wait_for_timeout(1_200)

        next_button = page.get_by_text(re.compile(r"^(Дальше|Следующая)$", re.IGNORECASE))
        if stable_rounds >= 2 and next_button.count():
            try:
                next_button.last.click(timeout=3_000)
                page.wait_for_timeout(1_500)
                stable_rounds = 0
            except Exception:
                pass

    return title, reviews[:reviews_limit]


def fetch_product_data_and_reviews(
    product_url_or_id: str, reviews_limit: int = 200
) -> Tuple[Optional[list[str]], Optional[str], Optional[str]]:
    product_id = get_product_id_from_url(product_url_or_id)
    if not product_id:
        return None, None, "Не удалось извлечь артикул Ozon из ссылки."

    if product_url_or_id.strip().isdigit():
        reviews_url = f"https://www.ozon.ru/product/{product_id}/reviews/"
    else:
        base = product_url_or_id.split("?", 1)[0].rstrip("/")
        reviews_url = base if base.endswith("/reviews") else f"{base}/reviews"
        reviews_url += "/"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, None, (
            "Для Ozon не установлен браузерный модуль. Выполните: "
            "pip install playwright && playwright install chromium"
        )

    profile_dir = Path.home() / "Library" / "Application Support" / "OzonReviewAnalyzer"
    profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                locale="ru-RU",
                viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(reviews_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_000)

            page_text = page.locator("body").inner_text(timeout=10_000)
            if "Похоже, нет соединения" in page_text:
                context.close()
                return None, None, "Ozon не открыл страницу. Проверьте интернет или VPN."
            if "Подтвердите, что вы не робот" in page_text:
                page.wait_for_timeout(20_000)

            title, reviews = _extract_page(page, reviews_limit)
            context.close()
    except Exception as exc:
        logger.exception("Не удалось получить отзывы Ozon")
        message = str(exc)
        if "Executable doesn't exist" in message:
            message = "Браузер не установлен. Выполните: playwright install chromium"
        return None, None, f"Не удалось загрузить Ozon: {message}"

    if not reviews:
        return [], title, (
            "Текстовые отзывы не найдены. Если Ozon показал проверку, пройдите её "
            "в открывшемся окне и повторите анализ."
        )
    return reviews, title, None
