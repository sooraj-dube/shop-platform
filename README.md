# shop-platform

Shared library for the shop services.

| Module | Contents |
|---|---|
| `shop_platform.events` | Event contracts and stream names |
| `shop_platform.messaging` | Redis Streams publisher and consumer, in-memory publisher for tests |
| `shop_platform.clients` | `InventoryClient`, `OrdersClient` |
| `shop_platform.http` | Base HTTP client: error mapping, retries for repeatable requests |
| `shop_platform.web` | FastAPI error format, `Idempotency-Key` header, `/healthz` |
| `shop_platform.db` | SQLite connection wrapper and ordered SQL migrations |
| `shop_platform.clock`, `shop_platform.ids` | Clock (real and fixed) and prefixed ids |

## Streams

| Stream | Producer | Event types |
|---|---|---|
| `orders.events` | shop-orders | `order.confirmed`, `order.cancelled` |
| `warehouse.events` | shop-warehouse | `goods.received`, `shipment.dispatched` |
| `returns.events` | shop-returns | `return.inspected` |

Consumers read with a consumer group named after the service. A handler that raises
leaves the message pending; it is retried after `retry_after_ms` and moved to
`<stream>.dead` after `max_attempts` deliveries.

## Error format

Every service answers errors as:

```json
{"error": {"code": "insufficient_stock", "message": "only 2 left"}}
```

`ServiceClient` maps 404 to `NotFound`, 409 to `Conflict`, other 4xx to `ServiceError`,
and connection failures, timeouts and 5xx to `ServiceUnavailable`. GETs and requests
with an `Idempotency-Key` are retried with backoff.

## Use from a service

```bash
pip install "shop-platform @ git+https://github.com/sooraj-dube/shop-platform@v0.3.0"
```

## Develop

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
```
