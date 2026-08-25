Приложение для выгрузки отзывов Ozon. Браузер открывается видимым, поэтому можно пройти captcha вручную. API отдаёт полный JSON-архив, который можно напрямую забирать мультиагентной системой.

## Возможности

- автоматическое определение Ozon или Wildberries по ссылке
- ввод артикула вручную с явным выбором маркетплейса
- настройка количества отзывов от 1 до 5000
- структурированный анализ через Gemini 2.5 Flash
- итоговый вердикт "Лучше брать", "Можно брать с оговорками" или "Лучше не брать"
- краткое объяснение рекомендации на основании повторяющихся отзывов
- отдельные кнопки копирования в заголовках плюсов и минусов
- понятные сообщения об ошибках
- постоянная браузерная сессия Ozon для прохождения защиты сайта

## Формат выгрузки

Базы данных и таблицы нет: один товар сохраняется в один файл `output/<article>.json`. Запись атомарная, поэтому мультиагентная система не увидит недописанный JSON.

```json
{
  "schema_version": "1.0",
  "job": {},
  "product": {
    "requested_url": "https://www.ozon.ru/product/2608237202/",
    "source_url": "https://www.ozon.ru/product/2608237202/reviews/",
    "article": "2608237202",
    "name": "Название товара",
    "category_path": ["Дом и сад", "Посуда", "Грили"],
    "brand": "Бренд",
    "seller": "Продавец",
    "price": "19990",
    "rating": "4.8",
    "reviews_count": 124,
    "fetched_at": "2026-08-25T10:00:00+00:00"
  },
  "reviews": [
    {
      "review_id": "review-id-or-null",
      "author": "Имя",
      "rating": 5,
      "date": "2026-08-20",
      "text": "Текст отзыва",
      "pros": "Быстро нагревается",
      "cons": "Короткий кабель",
      "purchased": true,
      "likes": 3,
      "dislikes": 0,
      "photos": ["https://..."],
      "videos": []
    }
  ],
  "analysis_reviews": [
    {
      "text": "Текст отзыва",
      "pros": "Быстро нагревается",
      "cons": "Короткий кабель",
      "rating": 5
    }
  ],
  "warnings": []
}
```

`null` означает, что Ozon поле не отдал. Пустой массив означает, что медиа нет. Отзывы без `review_id` сохраняются; дубликаты удаляются только по непустому `review_id`, не по тексту.

## API

Подробный контракт и примеры запросов находятся в [docs/API.md](docs/API.md).

Запуск локально:

```bash
pip install -r requirements.txt
playwright install chromium
API_TOKEN=change-me uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Создать задачу:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H 'Authorization: Bearer change-me' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: product-2608237202' \
  -d '{"article":"2608237202","max_reviews":200,"timeout_seconds":600}'
```

Затем мультиагентная система опрашивает `GET /api/v1/jobs/<job_id>` и забирает `GET /api/v1/jobs/<job_id>/result` после статуса `succeeded` или `partial`.

Очередь однопоточная: одновременно работает один Chrome. Redis, PostgreSQL и S3 не нужны. По умолчанию сохраняется до 200 отзывов, максимум — 5000; таймаут по умолчанию 600 секунд, максимум — 2800.

Переменные окружения:

- `API_TOKEN` — Bearer-токен для защищённых endpoint'ов;
- `OZON_OUTPUT_DIR` — каталог JSON, по умолчанию `output`;
- `OZON_PROFILE_DIR` — постоянный профиль Chrome;
- `OZON_PROXY_URL` — прокси для браузера;
- `PROXY_ROTATE_URL` — заранее настроенный endpoint смены IP;
- `PROXY_ROTATE_METHOD` — `POST` по умолчанию, можно `GET`;
- `PROXY_ROTATE_TOKEN` — токен сервиса ротации, не попадает в логи и JSON.

`/healthz` публичный. Остальные endpoint'ы требуют Bearer-токен. Для внешнего доступа ставьте reverse proxy с TLS; встроенный Uvicorn рассчитан на локальный запуск.
