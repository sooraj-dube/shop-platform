"""Event contracts shared across services.

Each producing service writes to its own stream. Consumers read a stream with a
consumer group named after the consuming service.
"""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

ORDERS_STREAM = "orders.events"
WAREHOUSE_STREAM = "warehouse.events"
RETURNS_STREAM = "returns.events"


def _event_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Event(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    EVENT_TYPE: ClassVar[str]

    event_id: str = Field(default_factory=_event_id)
    occurred_at: datetime = Field(default_factory=_utcnow)


class ShippingAddress(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=200)
    line1: str = Field(min_length=1, max_length=200)
    line2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    postal_code: str = Field(min_length=1, max_length=20)
    country: str = Field(pattern=r"^[A-Z]{2}$")


class OrderLineItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    line_id: str
    sku: str
    quantity: int = Field(gt=0)
    reservation_id: str


class CancelReason(StrEnum):
    CUSTOMER_REQUEST = "customer_request"
    FRAUD_REVIEW = "fraud_review"
    MERCHANT_REQUEST = "merchant_request"


class OrderConfirmed(Event):
    EVENT_TYPE: ClassVar[str] = "order.confirmed"

    order_id: str
    customer_id: str
    lines: list[OrderLineItem] = Field(min_length=1)
    shipping_address: ShippingAddress


class OrderCancelled(Event):
    EVENT_TYPE: ClassVar[str] = "order.cancelled"

    order_id: str
    reason: CancelReason
    lines: list[OrderLineItem] = Field(min_length=1)


class ShipmentDispatched(Event):
    EVENT_TYPE: ClassVar[str] = "shipment.dispatched"

    shipment_id: str
    order_id: str
    carrier: str
    tracking_number: str
    dispatched_at: datetime
    lines: list[OrderLineItem] = Field(min_length=1)


class ReceivedLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    sku: str
    quantity: int = Field(gt=0)


class GoodsReceived(Event):
    EVENT_TYPE: ClassVar[str] = "goods.received"

    receipt_id: str
    purchase_order_id: str
    supplier_id: str
    lines: list[ReceivedLine] = Field(min_length=1)


class ItemCondition(StrEnum):
    NEW = "new"
    OPENED = "opened"
    DAMAGED = "damaged"


class InspectedLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    line_id: str
    sku: str
    quantity: int = Field(gt=0)
    condition: ItemCondition
    restock: bool


class ReturnInspected(Event):
    EVENT_TYPE: ClassVar[str] = "return.inspected"

    return_id: str
    order_id: str
    lines: list[InspectedLine] = Field(min_length=1)


EVENT_TYPES: dict[str, type[Event]] = {
    cls.EVENT_TYPE: cls
    for cls in (
        OrderConfirmed,
        OrderCancelled,
        ShipmentDispatched,
        GoodsReceived,
        ReturnInspected,
    )
}


class UnknownEventType(ValueError):
    pass


def encode(event: Event) -> dict[str, str]:
    """Stream message fields for an event."""
    return {
        "event_type": event.EVENT_TYPE,
        "event_id": event.event_id,
        "data": event.model_dump_json(),
    }


def decode(fields: Mapping[str, str]) -> Event:
    """Rebuild an event from stream message fields.

    Raises ``UnknownEventType`` for types this version of the library does not know,
    and pydantic's ``ValidationError`` for a known type with a bad payload.
    """
    event_type = fields.get("event_type", "")
    cls = EVENT_TYPES.get(event_type)
    if cls is None:
        raise UnknownEventType(event_type)
    return cls.model_validate_json(fields["data"])
