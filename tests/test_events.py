import pytest
from pydantic import ValidationError

from shop_platform.events import (
    EVENT_TYPES,
    CancelReason,
    GoodsReceived,
    OrderCancelled,
    OrderLineItem,
    ReceivedLine,
    UnknownEventType,
    decode,
    encode,
)


def _cancelled() -> OrderCancelled:
    return OrderCancelled(
        order_id="ord_1",
        reason=CancelReason.CUSTOMER_REQUEST,
        lines=[OrderLineItem(line_id="lin_1", sku="SKU-1", quantity=2, reservation_id="res_1")],
    )


def test_round_trip_keeps_type_and_fields() -> None:
    event = _cancelled()
    decoded = decode(encode(event))
    assert isinstance(decoded, OrderCancelled)
    assert decoded == event


def test_encode_exposes_type_and_id_for_routing() -> None:
    event = GoodsReceived(
        receipt_id="rcp_1",
        purchase_order_id="po_1",
        supplier_id="sup_1",
        lines=[ReceivedLine(sku="SKU-1", quantity=10)],
    )
    fields = encode(event)
    assert fields["event_type"] == "goods.received"
    assert fields["event_id"] == event.event_id


def test_unknown_type_is_reported() -> None:
    with pytest.raises(UnknownEventType):
        decode({"event_type": "order.teleported", "event_id": "x", "data": "{}"})


def test_bad_payload_for_known_type_fails_validation() -> None:
    with pytest.raises(ValidationError):
        decode({"event_type": "order.cancelled", "event_id": "x", "data": '{"order_id": "o"}'})


def test_every_event_type_is_unique() -> None:
    assert len(EVENT_TYPES) == len({cls.__name__ for cls in EVENT_TYPES.values()})


def test_lines_must_not_be_empty() -> None:
    with pytest.raises(ValidationError):
        OrderCancelled(order_id="ord_1", reason=CancelReason.FRAUD_REVIEW, lines=[])
