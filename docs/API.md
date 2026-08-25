# Ozon Review Archive API

API предназначен для мультиагентной системы: она создаёт задачу, ждёт её завершения и забирает стабильный JSON-архив. API не вызывает Gemini и не навязывает конкретный анализатор.

## Запуск

```bash
pip install -r requirements.txt
playwright install chromium
export API_TOKEN='replace-with-a-long-random-token'
export OZON_OUTPUT_DIR='/srv/ozon-output'
uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Swagger и OpenAPI доступны на `/docs` и `/openapi.json`. Проверка живого сервиса:

```bash
curl http://127.0.0.1:8000/api/v1/healthz
# {"status":"ok"}
```

## Авторизация

Все endpoint'ы, кроме `/api/v1/healthz`, требуют:

```http
Authorization: Bearer <API_TOKEN>
```

`/api/v1/healthz` публичный. Если `API_TOKEN` не задан, остальные endpoint'ы закрыты для всех запросов. Токен не хранится в job/result и не выводится в лог.

## Создание задачи

`POST /api/v1/jobs` возвращает `202 Accepted` и ставит задачу в однопоточную очередь.

Тело:

```json
{
  "url": "https://www.ozon.ru/product/2608237202/",
  "article": "2608237202",
  "max_reviews": 200,
  "timeout_seconds": 600,
  "fresh_profile": false
}
```

Можно передать только `url` или только `article`. Если переданы оба поля, артикулы должны совпадать; иначе API вернёт `400`. `max_reviews` принимает 1–5000, дефолт 200. `timeout_seconds` принимает 1–2800, дефолт 600.

`fresh_profile=true` создаёт отдельный временный профиль только для этой попытки и удаляет его после закрытия Chrome. Постоянный `OZON_PROFILE_DIR` с пройденной CAPTCHA не удаляется.

Дефолты и серверные максимумы можно задать до старта процесса через `DEFAULT_MAX_REVIEWS`, `MAX_MAX_REVIEWS`, `DEFAULT_TIMEOUT_SECONDS` и `MAX_TIMEOUT_SECONDS`. Жёсткие верхние границы остаются 5000 и 2800.

Для повторного безопасного вызова используйте `Idempotency-Key`. Одинаковый ключ возвращает ту же задачу, пока сервис живёт.

Пример:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H 'Authorization: Bearer replace-with-a-long-random-token' \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: ozon-2608237202-20260825' \
  -d '{
    "article": "2608237202",
    "max_reviews": 200,
    "timeout_seconds": 600
  }'
```

То же на Python:

```python
import os
import time

import requests

base_url = "http://127.0.0.1:8000"
headers = {"Authorization": f"Bearer {os.environ['API_TOKEN']}"}
response = requests.post(
    f"{base_url}/api/v1/jobs",
    headers=headers,
    json={"article": "138342427", "max_reviews": 5, "timeout_seconds": 600},
    timeout=30,
)
response.raise_for_status()
job_id = response.json()["id"]

while True:
    response = requests.get(
        f"{base_url}/api/v1/jobs/{job_id}", headers=headers, timeout=30
    )
    response.raise_for_status()
    job = response.json()
    if job["status"] in {"succeeded", "partial", "failed", "cancelled"}:
        break
    time.sleep(1)

if job["status"] not in {"succeeded", "partial"}:
    raise RuntimeError(job["error"] or job["status"])

response = requests.get(
    f"{base_url}/api/v1/jobs/{job_id}/result", headers=headers, timeout=30
)
response.raise_for_status()
archive = response.json()
print(archive["product"]["article"], len(archive["reviews"]))
```

Ответ:

```json
{
  "id": "8c0d...",
  "status": "queued",
  "url": null,
  "article": "2608237202",
  "max_reviews": 200,
  "timeout_seconds": 600,
  "fresh_profile": false,
  "attempt": 0,
  "retry_count": 0,
  "proxy_rotated": false,
  "reviews_collected": 0,
  "warnings": [],
  "error": null
}
```

## Жизненный цикл

Статусы:

- `queued` — задача стоит в очереди;
- `running` — видимый Chrome загружает карточку;
- `waiting_for_captcha` — нужна ручная проверка в окне Chrome;
- `succeeded` — архив собран, есть отзывы;
- `partial` — задача завершилась, но отзывов нет или данных недостаточно;
- `failed` — техническая ошибка;
- `cancelled` — отменена пользователем.

Проверка:

```bash
curl http://127.0.0.1:8000/api/v1/jobs/8c0d... \
  -H 'Authorization: Bearer replace-with-a-long-random-token'
```

## Получение результата

`GET /api/v1/jobs/{job_id}/result` возвращает полный envelope только для `succeeded` или `partial`. До этого будет `409`.

```bash
curl http://127.0.0.1:8000/api/v1/jobs/8c0d.../result \
  -H 'Authorization: Bearer replace-with-a-long-random-token' \
  -o 2608237202.json
```

Основные поля envelope:

```text
schema_version     версия контракта, сейчас "1.0"
job                снимок задачи и попытки
product            URL, артикул, название, категория, бренд, продавец и сводка
reviews            полный архив отзывов
analysis_reviews   text + pros + cons + rating для анализа агентами
warnings           непустые предупреждения без потери результата
```

`product.category_path` равен `null`, если категорию не удалось получить. У неизвестных scalar-полей отзывов значение `null`, у `photos` и `videos` — `[]`.

Файл также сохраняется локально как `OZON_OUTPUT_DIR/<article>.json`. В БД, Redis и S3 сервис не пишет; хранение бессрочное до ручного удаления файла.

Воспроизводимый smoke-тест полного API-пути:

```bash
API_TOKEN=replace-with-a-long-random-token python scripts/live_smoke.py
```

Скрипт по умолчанию отправляет артикул `138342427`, ждёт терминальный статус и проверяет API-ответ и локальный JSON. Другой адрес API или артикул можно передать через `--base-url` и `--article`.

## Управление задачей

Отменить:

```http
POST /api/v1/jobs/{job_id}/cancel
```

Отмена выставляет `cancelled` и прерывает ожидание парсера при ближайшей проверке. Уже завершённая задача не отменяется.

Повторить:

```http
POST /api/v1/jobs/{job_id}/retry
```

Повтор доступен для `failed` и `partial`, максимум один раз. Автоматических бесконечных retry нет. Результат предыдущей попытки перед retry очищается.

Сменить IP:

```http
POST /api/v1/jobs/{job_id}/rotate-proxy
```

Ротация доступна в `waiting_for_captcha` или после `failed`. Она вызывает заранее настроенный `PROXY_ROTATE_URL` и выставляет `proxy_rotated=true`; для captcha после этого вызов `/retry` остановит старый browser wait и запустит новую попытку с уже сменившимся IP. Произвольный URL из тела запроса не принимается.

Если сервис ротации не настроен или вернул ошибку, API отвечает `502`; тело ответа провайдера наружу не попадает.

Настройки ротации:

```bash
export PROXY_ROTATE_URL='https://proxy-provider.example/rotate'
export PROXY_ROTATE_METHOD='POST'
export PROXY_ROTATE_TOKEN='provider-token'
```

Токен провайдера и URL не попадают в ответ API, архив или технические логи.

## Ограничения текущего worker'а

- Один процесс держит одну очередь и один persistent Chrome.
- После перезапуска процесса in-memory jobs теряются, но уже записанные JSON-файлы остаются.
- Внешний listener по умолчанию привязан к `127.0.0.1`.
- Парсер использует видимый браузер и DOM Ozon, а не официальный API; изменения защиты или разметки Ozon могут потребовать обновления адаптеров.
