from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from shop_platform.events import ShippingAddress
from shop_platform.http import ServiceClient


class PaymentMethod(StrEnum):
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"


class OrderStatus(StrEnum):
    AWAITING_PAYMENT = "awaiting_payment"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class NewOrderLine(BaseModel):
    sku: str
    name: str
    quantity: int = Field(gt=0)
    unit_price_cents: int = Field(ge=0)
    reservation_id: str


class NewOrder(BaseModel):
    customer_id: str
    payment_method: PaymentMethod
    payment_reference: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    lines: list[NewOrderLine] = Field(min_length=1)
    subtotal_cents: int = Field(ge=0)
    discount_cents: int = Field(ge=0)
    shipping_cents: int = Field(ge=0)
    tax_cents: int = Field(ge=0)
    total_cents: int = Field(ge=0)
    shipping_address: ShippingAddress


class OrderLine(BaseModel):
    model_config = ConfigDict(extra="ignore")

    line_id: str
    sku: str
    name: str
    quantity: int
    unit_price_cents: int
    reservation_id: str


class Order(BaseModel):
    """An order as the orders service returns it.

    ``status`` is a plain string so that a client built against an older version of
    this library still reads orders in statuses it does not know about.
    """

    model_config = ConfigDict(extra="ignore")

    order_id: str
    customer_id: str
    status: str
    payment_method: str
    payment_reference: str | None = None
    currency: str
    lines: list[OrderLine]
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    tax_cents: int
    total_cents: int
    shipping_address: ShippingAddress
    placed_at: datetime
    confirmed_at: datetime | None = None
    shipped_at: datetime | None = None
    cancelled_at: datetime | None = None


class OrdersClient(ServiceClient):
    """Client for the orders service's HTTP API."""

    def __init__(self, base_url: str, **kwargs: Any) -> None:
        super().__init__(base_url, service_name="orders", **kwargs)

    def create_order(self, order: NewOrder, *, idempotency_key: str) -> Order:
        data = self.request(
            "POST", "/orders", json=order.model_dump(mode="json"), idempotency_key=idempotency_key
        )
        return Order.model_validate(data)

    def get_order(self, order_id: str) -> Order:
        return Order.model_validate(self.request("GET", f"/orders/{order_id}"))
