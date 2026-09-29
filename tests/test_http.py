import httpx
import pytest

from shop_platform.clients import (
    InsufficientStock,
    InventoryClient,
    ReservationExpired,
)
from shop_platform.http import Conflict, NotFound, ServiceClient, ServiceUnavailable

RESERVATION = {
    "reservation_id": "res_1",
    "sku": "SKU-1",
    "quantity": 2,
    "status": "held",
    "created_at": "2026-05-01T10:00:00Z",
    "expires_at": "2026-05-01T10:15:00Z",
}


def _client(cls, handler, **kwargs):
    return cls("http://svc", transport=httpx.MockTransport(handler), sleep=lambda s: None, **kwargs)


def test_get_is_retried_on_server_error() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    client = _client(ServiceClient, handler, service_name="svc")
    assert client.request("GET", "/thing") == {"ok": True}
    assert len(calls) == 3


def test_write_without_idempotency_key_is_not_retried() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(502)

    client = _client(ServiceClient, handler, service_name="svc")
    with pytest.raises(ServiceUnavailable):
        client.request("POST", "/thing", json={})
    assert len(calls) == 1


def test_connection_errors_become_service_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = _client(ServiceClient, handler, service_name="svc", retries=1)
    with pytest.raises(ServiceUnavailable):
        client.request("GET", "/thing")


def test_error_body_is_mapped_to_exceptions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/missing":
            return httpx.Response(404, json={"error": {"code": "not_found", "message": "no"}})
        return httpx.Response(409, json={"error": {"code": "wrong_state", "message": "no"}})

    client = _client(ServiceClient, handler, service_name="svc")
    with pytest.raises(NotFound):
        client.request("GET", "/missing")
    with pytest.raises(Conflict) as exc:
        client.request("POST", "/other", idempotency_key="key-12345")
    assert exc.value.code == "wrong_state"


def test_inventory_reserve_sends_idempotency_key() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("Idempotency-Key")
        seen["body"] = request.read()
        return httpx.Response(201, json=RESERVATION)

    client = _client(InventoryClient, handler)
    reservation = client.reserve("SKU-1", 2, idempotency_key="chk_1:SKU-1")
    assert reservation.reservation_id == "res_1"
    assert seen["key"] == "chk_1:SKU-1"
    assert b'"hold_seconds"' not in seen["body"]


@pytest.mark.parametrize(
    ("code", "error"),
    [("insufficient_stock", InsufficientStock), ("reservation_expired", ReservationExpired)],
)
def test_inventory_conflicts_have_specific_types(code: str, error: type[Exception]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": {"code": code, "message": "x"}})

    client = _client(InventoryClient, handler)
    with pytest.raises(error):
        client.commit(["res_1"], idempotency_key="chk_1:commit")
