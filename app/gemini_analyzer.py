from __future__ import annotations

import json
import logging
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiAnalyzer:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API ключ Gemini не предоставлен.")
        self.client = genai.Client(api_key=api_key)
        self.model_name = "gemini-2.5-flash"

    def analyze_reviews(
        self, reviews: list[str], product_name: str = "товар"
    ) -> tuple[Optional[dict[str, object]], Optional[str]]:
        if not reviews:
            return None, "Список отзывов пуст для анализа."

        chunks: list[str] = []
        current_length = 0
        for index, review in enumerate(reviews, start=1):
            item = f"Отзыв {index}: {review.strip()}"
            if current_length + len(item) > 180_000:
                break
            chunks.append(item)
            current_length += len(item)

        prompt = (
            f"Проанализируй отзывы о товаре «{product_name}». Выдели до 10 наиболее "
            "значимых и повторяющихся плюсов и до 10 минусов. Объединяй дубли, не "
            "выдумывай факты и не включай единичные бессодержательные реплики. "
            "Формулировки должны быть короткими и полезными покупателю. В конце "
            "дай итоговый вердикт: «Лучше брать», «Можно брать с оговорками» или "
            "«Лучше не брать». Объясни его одним-двумя предложениями, опираясь "
            "только на повторяющиеся факты из отзывов.\n\n"
            + "\n\n".join(chunks)
        )

        schema = {
            "type": "object",
            "properties": {
                "pros": {"type": "array", "items": {"type": "string"}},
                "cons": {"type": "array", "items": {"type": "string"}},
                "recommendation": {
                    "type": "object",
                    "properties": {
                        "verdict": {
                            "type": "string",
                            "enum": [
                                "Лучше брать",
                                "Можно брать с оговорками",
                                "Лучше не брать",
                            ],
                        },
                        "reason": {"type": "string"},
                    },
                    "required": ["verdict", "reason"],
                },
            },
            "required": ["pros", "cons", "recommendation"],
        }

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                ),
            )
            if not response.text:
                return None, "Gemini вернул пустой ответ."
            result = json.loads(response.text)
            recommendation = result.get("recommendation", {})
            return {
                "pros": [str(item).strip() for item in result.get("pros", []) if str(item).strip()],
                "cons": [str(item).strip() for item in result.get("cons", []) if str(item).strip()],
                "recommendation": {
                    "verdict": str(recommendation.get("verdict", "")).strip(),
                    "reason": str(recommendation.get("reason", "")).strip(),
                },
            }, None
        except Exception as exc:
            logger.exception("Ошибка Gemini при анализе '%s'", product_name)
            message = str(exc)
            if "API_KEY_INVALID" in message or "API key not valid" in message:
                message = "Недействительный GEMINI_API_KEY."
            return None, f"Ошибка Gemini API: {message}"
