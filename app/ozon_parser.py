from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

PRODUCT_ID_PATTERNS = (
    re.compile(r"/product/(?:[^/?#]*-)?(\d{6,})(?:[/ ?#]|$)", re.IGNORECASE),
    re.compile(r"/product/(\d{6,})(?:[/ ?#]|$)", re.IGNORECASE),
)
SCHEMA_VERSION = "1.0"
OZON_HOSTS = frozenset({"ozon.ru", "www.ozon.ru", "m.ozon.ru"})


def _configured_limit(name: str, default: int, upper_bound: int) -> int:
    raw_value = os.getenv(name)
    value = default if raw_value is None else int(raw_value)
    if not 1 <= value <= upper_bound:
        raise ValueError(f"{name} должен быть от 1 до {upper_bound}.")
    return value


MAX_REVIEWS_LIMIT = _configured_limit("MAX_MAX_REVIEWS", 5_000, 5_000)
DEFAULT_REVIEWS_LIMIT = _configured_limit("DEFAULT_MAX_REVIEWS", 200, MAX_REVIEWS_LIMIT)
MAX_TIMEOUT_SECONDS = _configured_limit("MAX_TIMEOUT_SECONDS", 2_800, 2_800)
DEFAULT_TIMEOUT_SECONDS = _configured_limit(
    "DEFAULT_TIMEOUT_SECONDS", 600, MAX_TIMEOUT_SECONDS
)


class OzonFetchCancelled(Exception):
    pass


class OzonFetchTimeout(Exception):
    pass


@contextmanager
def _profile_directory(fresh_profile: bool) -> Iterator[Path]:
    persistent_profile = Path(
        os.getenv("OZON_PROFILE_DIR", str(Path.home() / ".ozon-review-analyzer"))
    )
    if fresh_profile:
        with tempfile.TemporaryDirectory(prefix="ozon-profile-") as directory:
            yield Path(directory)
        return
    persistent_profile.mkdir(parents=True, exist_ok=True)
    yield persistent_profile


def get_product_id_from_url(value: str) -> str | None:
    candidate = value.strip()
    if candidate.isdigit():
        return candidate
    for pattern in PRODUCT_ID_PATTERNS:
        match = pattern.search(candidate)
        if match:
            return match.group(1)
    return None


def is_allowed_ozon_url(value: str) -> bool:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname in OZON_HOSTS
        and port is None
        and parsed.username is None
        and parsed.password is None
    )


def sanitize_error(value: Any) -> str:
    message = str(value)
    message = re.sub(
        r"(?i)(https?://)([^/\s:@]+):([^@\s/]+)@",
        r"\1***:***@",
        message,
    )
    for name in (
        "API_TOKEN",
        "OZON_PROXY_URL",
        "PROXY_ROTATE_URL",
        "PROXY_ROTATE_TOKEN",
    ):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "***")
    return message[:500]


def _json_nodes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        nodes = [value]
        graph = value.get("@graph")
        if isinstance(graph, list):
            nodes.extend(node for node in graph if isinstance(node, dict))
        return nodes
    if isinstance(value, list):
        return [node for item in value for node in _json_nodes(item)]
    return []


def _json_text(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("name") or value.get("value")
    return value


def _json_number(value: Any) -> Any:
    if value is None or isinstance(value, (int, float)):
        return value
    return str(value).strip() or None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    match = re.search(r"\d[\d\s\u00a0]*", str(value))
    return int(re.sub(r"\D", "", match.group(0))) if match else None


def _as_decimal(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    if not match:
        return None
    number = match.group(0).replace(",", ".")
    return float(number) if "." in number else int(number)


def _price_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    matches = re.findall(r"\d[\d\s\u00a0]*\s*(?:₽|руб)", value, re.IGNORECASE)
    return _as_int(matches[-1]) if matches else value.strip() or None


def _category_values(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"\s*(?:>|/|→)\s*", value)]
        return [part for part in parts if part] or None
    if isinstance(value, list):
        result = [str(_json_text(item)).strip() for item in value if _json_text(item)]
        return result or None
    return None


def parse_product_jsonld(payloads: list[str]) -> dict[str, Any]:
    product: dict[str, Any] = {}
    for payload in payloads:
        try:
            parsed = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            continue
        for node in _json_nodes(parsed):
            node_type = node.get("@type")
            types = node_type if isinstance(node_type, list) else [node_type]
            if "Product" not in types:
                continue
            for key, value in (
                ("name", node.get("name")),
                ("brand", _json_text(node.get("brand"))),
                ("seller", _json_text(node.get("seller"))),
            ):
                if value is not None and str(value).strip():
                    product[key] = value
            category = _category_values(node.get("category"))
            if category:
                product["category_path"] = category
            offers = node.get("offers")
            if isinstance(offers, list):
                offers = offers[0] if offers else None
            if isinstance(offers, dict):
                if "price" in offers:
                    product["price"] = _json_number(offers["price"])
                if "seller" not in product and offers.get("seller"):
                    product["seller"] = _json_text(offers["seller"])
            aggregate = node.get("aggregateRating")
            if isinstance(aggregate, dict):
                if aggregate.get("ratingValue") is not None:
                    product["rating"] = _json_number(aggregate["ratingValue"])
                if aggregate.get("reviewCount") is not None:
                    product["reviews_count"] = _json_number(aggregate["reviewCount"])
    return product


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def make_review_record(
    review_id: str | None,
    text: str | None,
    *,
    author: str | None = None,
    rating: Any = None,
    date: str | None = None,
    pros: str | None = None,
    cons: str | None = None,
    purchased: bool | None = None,
    likes: Any = None,
    dislikes: Any = None,
    photos: list[Any] | None = None,
    videos: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "review_id": review_id,
        "author": author,
        "rating": rating,
        "date": date,
        "text": text,
        "pros": pros,
        "cons": cons,
        "purchased": purchased,
        "likes": likes,
        "dislikes": dislikes,
        "photos": _as_list(photos),
        "videos": _as_list(videos),
    }


def project_for_analysis(reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "text": review.get("text"),
            "pros": review.get("pros"),
            "cons": review.get("cons"),
            "rating": review.get("rating"),
        }
        for review in reviews
    ]


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
    result = " ".join(useful).strip()
    return re.sub(r"\s*[.…]+\s*Читать полностью\s*$", "", result).strip()


def _locator_text(locator: Any, timeout: int = 1_000) -> str | None:
    try:
        if not locator.count():
            return None
        value = locator.first.text_content(timeout=timeout)
    except Exception:  # noqa: BLE001 - Playwright raises several browser errors.
        return None
    value = re.sub(r"\s+", " ", value or "").strip()
    return value or None


def _locator_attribute(locator: Any, attribute: str) -> str | None:
    try:
        if not locator.count():
            return None
        value = locator.first.get_attribute(attribute)
    except Exception:  # noqa: BLE001 - Playwright raises several browser errors.
        return None
    return value.strip() if value and value.strip() else None


def _first_text(node: Any, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        value = _locator_text(node.locator(selector))
        if value:
            return value
    return None


def _labeled_value(raw_text: str, labels: tuple[str, ...]) -> str | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:{label_pattern})\s*:?\s*(.+?)(?=\s+(?:Достоинства|Плюсы|Недостатки|Минусы|Вам помог|$))",
        raw_text,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _number_after_label(raw_text: str, labels: tuple[str, ...]) -> int | None:
    label_pattern = "|".join(re.escape(label) for label in labels)
    match = re.search(rf"(?:{label_pattern})[^\d]?(\d+)", raw_text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _rating_from_node(node: Any, raw_text: str) -> Any:
    for selector in ("[data-rating]", "[itemprop='ratingValue']"):
        value = _locator_attribute(
            node.locator(selector), "data-rating"
        ) or _locator_text(node.locator(selector))
        if value:
            match = re.search(r"(?:^|\s)([1-5])(?:[,.]\d+)?(?:\s|$)", value)
            if match:
                return int(match.group(1))
    stars = node.locator("div[class*='jm4'] svg").count()
    if 1 <= stars <= 5:
        return stars
    for selector in (
        "[aria-label*='рейтинг']",
        "[aria-label*='звезд']",
        "[aria-label*='rating']",
    ):
        value = _locator_attribute(node.locator(selector), "aria-label")
        if value:
            match = re.search(r"([1-5])(?:[,.]\d+)?", value)
            if match:
                return int(match.group(1))
    match = re.search(r"(?:^|\s)([1-5])\s*(?:из\s*5|зв[её]зд)", raw_text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _extract_media(node: Any, selector: str, attributes: tuple[str, ...]) -> list[str]:
    result: list[str] = []
    try:
        count = node.locator(selector).count()
    except Exception:  # noqa: BLE001 - a detached review node is simply skipped.
        return result
    for index in range(count):
        item = node.locator(selector).nth(index)
        for attribute in attributes:
            value = _locator_attribute(item, attribute)
            if value and value not in result:
                result.append(value)
                break
    return result


def _extract_review_record(node: Any) -> dict[str, Any] | None:
    try:
        raw_text = node.inner_text(timeout=2_000)
    except Exception:  # noqa: BLE001 - a detached review node is simply skipped.
        return None
    text = _clean_review(raw_text)
    if not 15 <= len(text) <= 5_000:
        return None

    review_id = None
    for attribute in ("data-review-uuid", "data-review-id", "data-id"):
        try:
            review_id = node.get_attribute(attribute)
        except Exception:  # noqa: BLE001 - a detached review node is simply skipped.
            review_id = None
        if review_id:
            break

    date = _first_text(node, ("time", "[class*='date']", "[data-date]"))
    if date is None:
        date_match = re.search(r"\b\d{1,2} [а-яё]+ 20\d{2}\b", raw_text, re.IGNORECASE)
        date = date_match.group(0) if date_match else None

    purchased = None
    try:
        order_type = node.get_attribute("ordertype")
    except Exception:  # noqa: BLE001 - a detached review node is simply skipped.
        order_type = None
    if order_type == "1":
        purchased = True
    elif order_type == "0":
        purchased = False
    if re.search(r"(товар|покупка).{0,20}(куплен|подтвержд)", raw_text, re.IGNORECASE):
        purchased = True
    elif re.search(r"(товар|покупка).{0,20}не куплен", raw_text, re.IGNORECASE):
        purchased = False

    return make_review_record(
        review_id.strip() if review_id else None,
        text,
        author=_first_text(
            node,
            (
                "span[class*='tsCompactControl500Medium']",
                "[data-review-author]",
                "[class*='author']",
                "a[href*='/profile']",
            ),
        ),
        rating=_rating_from_node(node, raw_text),
        date=date,
        pros=_labeled_value(raw_text, ("Достоинства", "Плюсы")),
        cons=_labeled_value(raw_text, ("Недостатки", "Минусы")),
        purchased=purchased,
        likes=_number_after_label(raw_text, ("Да",)),
        dislikes=_number_after_label(raw_text, ("Нет",)),
        photos=_extract_media(
            node, "button[aria-label*='галер'] img", ("src", "data-src")
        ),
        videos=_extract_media(node, "video, video source", ("src", "poster")),
    )


def _page_title(page: Any) -> str:
    heading = _locator_text(page.locator("h1"), timeout=8_000) or ""
    title_lines = [line.strip() for line in heading.splitlines() if line.strip()]
    title = (
        title_lines[-1]
        if title_lines
        else f"Товар Ozon {get_product_id_from_url(page.url) or ''}".strip()
    )
    return re.sub(r"^Отзывы о товаре\s+\d+\s*", "", title).strip() or title


def _check_fetch_state(
    deadline: float,
    should_cancel: Callable[[], bool] | None,
) -> None:
    if should_cancel and should_cancel():
        raise OzonFetchCancelled
    if time.monotonic() >= deadline:
        raise OzonFetchTimeout


def _extract_page(
    page: Any,
    reviews_limit: int,
    deadline: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    title = _page_title(page)
    reviews: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    stable_rounds = 0

    while len(reviews) < reviews_limit and stable_rounds < 4:
        if deadline is not None:
            _check_fetch_state(deadline, should_cancel)
        elif should_cancel and should_cancel():
            raise OzonFetchCancelled
        before = len(reviews)
        candidates = page.locator("[data-review-uuid], [data-review-id]")
        if not candidates.count():
            candidates = page.locator("[data-widget='webListReviews'] > div > div")
        for index in range(min(candidates.count(), reviews_limit * 3)):
            if deadline is not None:
                _check_fetch_state(deadline, should_cancel)
            elif should_cancel and should_cancel():
                raise OzonFetchCancelled
            record = _extract_review_record(candidates.nth(index))
            if record is None:
                continue
            review_id = record["review_id"]
            if review_id is not None:
                if review_id in seen_ids:
                    continue
                seen_ids.add(review_id)
            reviews.append(record)
            if len(reviews) >= reviews_limit:
                break

        stable_rounds = stable_rounds + 1 if len(reviews) == before else 0
        page.mouse.wheel(0, 5_000)
        page.wait_for_timeout(1_200)

        next_button = page.get_by_text(
            re.compile(r"^(Дальше|Следующая)$", re.IGNORECASE)
        )
        if stable_rounds >= 2 and next_button.count():
            try:
                next_button.last.click(timeout=3_000)
                page.wait_for_timeout(1_500)
                stable_rounds = 0
            except Exception:
                logger.debug("Ozon review pagination click failed", exc_info=True)

    return title, reviews[:reviews_limit]


def _review_page_url(product_url_or_id: str, product_id: str) -> str:
    if product_url_or_id.strip().isdigit():
        return f"https://www.ozon.ru/product/{product_id}/reviews/"
    base = product_url_or_id.split("?", 1)[0].rstrip("/")
    return f"{base if base.endswith('/reviews') else f'{base}/reviews'}/"


def _all_text_contents(page: Any, selector: str) -> list[str]:
    try:
        return page.locator(selector).all_text_contents()
    except Exception:  # noqa: BLE001 - selectors vary between Ozon page versions.
        return []


def _collect_category_path(page: Any) -> list[str] | None:
    for selector in (
        "[data-widget='webBreadCrumbs'] a",
        "[data-widget='breadCrumbs'] a",
        "nav[aria-label*='хлеб'] a",
    ):
        values = [
            re.sub(r"\s+", " ", value).strip()
            for value in _all_text_contents(page, selector)
        ]
        values = [
            value
            for value in values
            if value and value.lower() not in {"главная", "ozon"}
        ]
        if values:
            return values
    return None


def _collect_product_metadata(
    page: Any,
    requested_url: str,
    product_id: str,
    title: str,
) -> dict[str, Any]:
    try:
        payloads = page.locator(
            "script[type='application/ld+json']"
        ).all_text_contents()
    except Exception:  # noqa: BLE001 - JSON-LD is optional on the page.
        payloads = []
    structured = parse_product_jsonld(payloads)
    category_path = _collect_category_path(page) or structured.get("category_path")
    price = _price_value(
        structured.get("price")
        or _first_text(
            page,
            ("[itemprop='price']", "[data-widget*='webPrice']", "[class*='price']"),
        )
    )
    rating = _as_decimal(
        structured.get("rating")
        or _first_text(page, ("[itemprop='ratingValue']", "[aria-label*='рейтинг']"))
    )
    reviews_count = _as_int(structured.get("reviews_count"))
    if reviews_count is None:
        body = _locator_text(page.locator("body"), timeout=5_000) or ""
        match = re.search(r"([\d\s\u00a0]+)\s+отзыв", body, re.IGNORECASE)
        reviews_count = _as_int(match.group(1)) if match else None

    brand = structured.get("brand") or _first_text(
        page, ("[itemprop='brand']", "[data-widget*='brand']")
    )
    seller = structured.get("seller") or _first_text(
        page,
        (
            "[data-widget='webSellerBrand'] a",
            "[data-widget*='seller'] a",
            "a[href*='/seller/']",
        ),
    )
    return {
        "requested_url": requested_url,
        "source_url": (page.url or requested_url).split("?", 1)[0],
        "article": product_id,
        "name": title or structured.get("name"),
        "category_path": category_path,
        "brand": brand,
        "seller": seller,
        "price": price,
        "rating": rating,
        "reviews_count": reviews_count,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def save_archive(archive: dict[str, Any], output_dir: str | Path | None = None) -> Path:
    target_dir = Path(output_dir or os.getenv("OZON_OUTPUT_DIR", "output"))
    target_dir.mkdir(parents=True, exist_ok=True)
    article = str(archive["product"]["article"])
    target = target_dir / f"{article}.json"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=target_dir,
        prefix=f".{article}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        json.dump(archive, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(target)
    return target


def fetch_product_archive_and_reviews(
    product_url_or_id: str,
    reviews_limit: int = DEFAULT_REVIEWS_LIMIT,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    fresh_profile: bool = False,
    on_captcha: Callable[[], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
    output_dir: str | Path | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not 1 <= reviews_limit <= MAX_REVIEWS_LIMIT:
        return None, f"reviews_limit должен быть от 1 до {MAX_REVIEWS_LIMIT}."
    if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        return None, f"timeout_seconds должен быть от 1 до {MAX_TIMEOUT_SECONDS}."

    product_id = get_product_id_from_url(product_url_or_id)
    if not product_id:
        return None, "Не удалось извлечь артикул Ozon из ссылки."
    if not product_url_or_id.strip().isdigit() and not is_allowed_ozon_url(
        product_url_or_id
    ):
        return None, "Ссылка должна быть HTTPS-адресом карточки Ozon."
    requested_url = (
        f"https://www.ozon.ru/product/{product_id}/"
        if product_url_or_id.strip().isdigit()
        else product_url_or_id.strip()
    )
    reviews_url = _review_page_url(product_url_or_id, product_id)
    deadline = time.monotonic() + timeout_seconds

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, (
            "Для Ozon не установлен браузерный модуль. Выполните: "
            "pip install playwright && playwright install chromium"
        )

    try:
        with (
            _profile_directory(fresh_profile) as profile_dir,
            sync_playwright() as playwright,
        ):
            proxy_url = os.getenv("OZON_PROXY_URL")
            launch_kwargs: dict[str, Any] = {
                "headless": False,
                "locale": "ru-RU",
                "viewport": {"width": 1280, "height": 900},
                "args": ["--disable-blink-features=AutomationControlled"],
            }
            if proxy_url:
                launch_kwargs["proxy"] = {"server": proxy_url}
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir), **launch_kwargs
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                _check_fetch_state(deadline, should_cancel)
                page.goto(
                    reviews_url,
                    wait_until="domcontentloaded",
                    timeout=max(
                        1_000, min(60_000, int((deadline - time.monotonic()) * 1_000))
                    ),
                )
                page.wait_for_timeout(2_000)
                _check_fetch_state(deadline, should_cancel)

                remaining_ms = max(100, int((deadline - time.monotonic()) * 1_000))
                page_text = (
                    _locator_text(
                        page.locator("body"), timeout=min(1_000, remaining_ms)
                    )
                    or ""
                )
                if "Похоже, нет соединения" in page_text:
                    return None, "Ozon не открыл страницу. Проверьте интернет или VPN."
                captcha_reported = False
                while re.search(
                    r"не робот|проверка безопасности|доступ ограничен|включите javascript",
                    page_text,
                    re.IGNORECASE,
                ):
                    _check_fetch_state(deadline, should_cancel)
                    if not captcha_reported:
                        captcha_reported = True
                        if on_captcha:
                            on_captcha()
                    remaining_ms = max(100, int((deadline - time.monotonic()) * 1_000))
                    page.wait_for_timeout(min(1_000, remaining_ms))
                    _check_fetch_state(deadline, should_cancel)
                    page_text = (
                        _locator_text(
                            page.locator("body"), timeout=min(1_000, remaining_ms)
                        )
                        or ""
                    )

                title, reviews = _extract_page(
                    page, reviews_limit, deadline=deadline, should_cancel=should_cancel
                )
                archive = {
                    "schema_version": SCHEMA_VERSION,
                    "job": {
                        "job_id": None,
                        "attempt": 1,
                        "proxy_rotated": False,
                    },
                    "product": _collect_product_metadata(
                        page, requested_url, product_id, title
                    ),
                    "reviews": reviews,
                    "analysis_reviews": project_for_analysis(reviews),
                    "warnings": [],
                }
                if not reviews:
                    archive["warnings"].append(
                        "Текстовые отзывы не найдены. Если Ozon показал проверку, пройдите её "
                        "в открывшемся окне и повторите анализ."
                    )
                save_archive(archive, output_dir)
                return archive, None
            finally:
                context.close()
    except OzonFetchCancelled:
        return None, "Задача отменена пользователем."
    except OzonFetchTimeout:
        return None, "Истёк таймаут загрузки Ozon."
    except Exception as exc:  # noqa: BLE001 - report browser/network failures safely.
        logger.error("Не удалось получить отзывы Ozon (%s)", type(exc).__name__)
        message = sanitize_error(exc)
        if "Executable doesn't exist" in message:
            message = "Браузер не установлен. Выполните: playwright install chromium"
        return None, f"Не удалось загрузить Ozon: {message}"


def fetch_product_data_and_reviews(
    product_url_or_id: str, reviews_limit: int = DEFAULT_REVIEWS_LIMIT
) -> tuple[list[str] | None, str | None, str | None]:
    archive, error = fetch_product_archive_and_reviews(product_url_or_id, reviews_limit)
    if error or archive is None:
        return None, None, error
    reviews = [review["text"] for review in archive["reviews"] if review.get("text")]
    return reviews, archive["product"].get("name"), None
