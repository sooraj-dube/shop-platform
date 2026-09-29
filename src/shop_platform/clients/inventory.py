from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from shop_platform.http import Conflict, ServiceClient


class ReservationStatus(StrEnum):
    HELD = "held"
    COMMITTED = "committed"
    RELEASED = "released"
    EXPIRED = "expired"
    FULFILLED = "fulfilled"


class Reservation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reservation_id: str
    sku: str
    quantity: int
    status: str
    created_at: datetime
    expires_at: datetime | None = None


class InsufficientStock(Conflict):
    pass


class ReservationExpired(Conflict):
    pass


_CONFLICTS: dict[str, type[Conflict]] = {
    "insufficient_stock": InsufficientStock,
    "reservation_expired": ReservationExpired,
}


class InventoryClient(ServiceClient):
    """Client for the inventory service's HTTP API."""

    def __init__(self, base_url: str, **kwargs: Any) -> None:
        super().__init__(base_url, service_name="inventory", **kwargs)

    def reserve(
        self, sku: str, quantity: int, *, idempotency_key: str, hold_seconds: int | None = None
    ) -> Reservation:
        body: dict[str, Any] = {"sku": sku, "quantity": quantity}
        if hold_seconds is not None:
            body["hold_seconds"] = hold_seconds
        return Reservation.model_validate(self._write("/reservations", body, idempotency_key))

    def commit(self, reservation_ids: list[str], *, idempotency_key: str) -> list[Reservation]:
        """Commit several holds together. Either every hold is committed or none is."""
        data = self._write(
            "/reservations/commit", {"reservation_ids": reservation_ids}, idempotency_key
        )
        return [Reservation.model_validate(item) for item in data["reservations"]]

    def release(self, reservation_id: str, *, idempotency_key: str) -> Reservation:
        data = self._write(f"/reservations/{reservation_id}/release", None, idempotency_key)
        return Reservation.model_validate(data)

    def get_reservation(self, reservation_id: str) -> Reservation:
        return Reservation.model_validate(self.request("GET", f"/reservations/{reservation_id}"))

    def _write(self, path: str, body: dict[str, Any] | None, idempotency_key: str) -> Any:
        try:
            return self.request("POST", path, json=body, idempotency_key=idempotency_key)
        except Conflict as exc:
            specific = _CONFLICTS.get(exc.code)
            if specific is None:
                raise
            raise specific(exc.status_code, exc.code, exc.message) from exc
