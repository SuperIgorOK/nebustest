# Асинхронный процессинг платежей

Тестовый микросервис на FastAPI, PostgreSQL и RabbitMQ. API принимает платёж,
сохраняет его вместе с outbox-событием, а один consumer эмулирует платёжный шлюз
и отправляет результат через webhook.

Стек: Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, PostgreSQL,
RabbitMQ, FastStream, Alembic, Docker Compose.

## Запуск

```bash
cp .env.example .env
docker compose up --build -d
```

Миграции применятся автоматически. После запуска доступны:

- API — http://localhost:8000
- Swagger — http://localhost:8000/docs
- AsyncAPI — http://localhost:8000/asyncapi
- RabbitMQ UI — http://localhost:15672 (`guest` / `guest`)

API и `/health` защищены заголовком `X-API-Key`. Локальное значение из
`.env.example` — `change-me`. Страницы документации оставлены открытыми для проверки.

## API

Создание платежа:

```bash
curl -X POST http://localhost:8000/api/v1/payments \
  -H 'X-API-Key: change-me' \
  -H 'Idempotency-Key: order-1' \
  -H 'Content-Type: application/json' \
  -d '{
    "amount": "100.00",
    "currency": "RUB",
    "description": "Order 1",
    "metadata": {"customer_id": 42},
    "webhook_url": "http://webhook-echo:9000/webhooks/payments"
  }'
```

Ответ — `202 Accepted` с `payment_id`, `status` и `created_at`.
Повтор того же запроса с тем же `Idempotency-Key` вернёт исходный платёж.
Если тело изменилось, API ответит `409 Conflict`.

Получение платежа:

```bash
curl http://localhost:8000/api/v1/payments/PAYMENT_ID \
  -H 'X-API-Key: change-me'
```

Поддерживаются валюты `RUB`, `USD`, `EUR`. Сумма должна быть положительной,
не более чем с двумя знаками после запятой.

Для локальной проверки webhook запустите необязательный echo-сервис:

```bash
docker compose --profile demo up --build -d webhook-echo
docker compose logs -f webhook-echo
```

## Поток обработки

```text
POST /api/v1/payments
        │
        ▼
PostgreSQL transaction
├── payments: pending
└── outbox: payments.new
        │
        ▼
Outbox publisher → RabbitMQ: payments.new
        │
        ▼
Consumer → gateway 2–5 сек. → succeeded 90% / failed 10%
        │
        ▼
UPDATE payment → webhook
        │
        ├── success → ACK
        ├── temporary error → retry через 1 сек. → retry через 2 сек. → DLQ
        └── permanent error → DLQ
```

Три попытки означают первоначальную обработку и два повтора. Платёжный `failed` —
нормальный результат шлюза: он сохраняется в БД и отправляется через webhook.

## Гонки и сбои

| Сценарий | Что делает сервис |
|---|---|
| Два запроса одновременно используют один ключ | Уникальное ограничение БД выбирает один платёж. Проигравшая транзакция перечитывает победителя. В результате создаются одна запись `payments` и одно событие `outbox`. |
| Один ключ приходит с другим телом | Сравнивается fingerprint значимых полей, API возвращает `409`. |
| Запись платежа успешна, а запись outbox падает | Обе записи находятся в одной транзакции, поэтому платёж тоже откатывается. |
| RabbitMQ недоступен | Событие остаётся `pending` в outbox и будет опубликовано следующим проходом. |
| Событие доставлено повторно | Для платежа с конечным статусом шлюз повторно не вызывается; consumer продолжает с webhook. Эмулятор также возвращает стабильный результат для одного payment ID. |
| Два обработчика пытаются отправить один webhook | Строка платежа блокируется на время ограниченного HTTP-вызова; после первой успешной доставки второй обработчик ничего не отправляет. |
| Webhook временно недоступен | Результат платежа и число попыток сохраняются до постановки сообщения в retry. Повтор не запускает шлюз заново. |
| Не удалось опубликовать retry или DLQ | Исходное сообщение не подтверждается: после короткой паузы выполняется `NACK/requeue`. |
| Webhook принят, но consumer упал до commit/ACK | Возможна повторная доставка. Webhook получает стабильный `X-Webhook-Id`, по которому получатель должен удалять дубли. |

Последний сценарий — нормальная граница гарантии at-least-once. Для настоящего
платёжного шлюза также потребуется его собственный idempotency key: процесс может
упасть после внешнего списания, но до сохранения статуса в нашей БД.

## Архитектура

- `app/domain/` — модель платежа и бизнес-инварианты без фреймворков.
- `app/application/` — сценарии и интерфейсы репозиториев, шлюза и webhook.
- `app/infrastructure/` — SQLAlchemy, HTTP, RabbitMQ и реализации интерфейсов.
- `app/api/` — HTTP-схемы, авторизация и маршруты FastAPI.
- `app/bootstrap.py` — сборка зависимостей.

В БД используются требуемые таблицы `payments` и `outbox`. Payment и outbox
создаются атомарно. Публикация считается успешной только после RabbitMQ publisher
confirm. Универсальный repository и DI-контейнер не добавлены: для этого сервиса
они увеличили бы объём кода без новой гарантии.

Полный контракт очередей, retry-заголовков и DLQ находится в
[`docs/asyncapi.yaml`](docs/asyncapi.yaml). Его можно открыть через `/asyncapi`
или скачать через `/asyncapi.yaml`.

## Проверки

```bash
uv sync --frozen
uv run ruff check .
uv run pytest
```

Интеграционные тесты требуют PostgreSQL и RabbitMQ:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/payments \
TEST_RABBITMQ_URL=amqp://guest:guest@localhost:5672/ \
uv run pytest
```

Тесты создают временные схемы и очереди. Отдельно проверяются конкурентная
идемпотентность, rollback payment/outbox, повторная доставка, блокировка webhook,
publisher confirms, retry и DLQ.

Остановка:

```bash
docker compose down
```
