import fakeredis
import pytest

from shop_platform.events import (
    ORDERS_STREAM,
    CancelReason,
    Event,
    OrderCancelled,
    OrderLineItem,
    encode,
)
from shop_platform.messaging import RedisStreamPublisher, StreamConsumer, Subscription


@pytest.fixture
def redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


def _event(order_id: str = "ord_1") -> OrderCancelled:
    return OrderCancelled(
        order_id=order_id,
        reason=CancelReason.CUSTOMER_REQUEST,
        lines=[OrderLineItem(line_id="lin_1", sku="SKU-1", quantity=1, reservation_id="res_1")],
    )


def _consumer(redis, handler, **kwargs) -> StreamConsumer:
    consumer = StreamConsumer(
        redis,
        group="inventory",
        consumer="test",
        subscriptions=[Subscription(ORDERS_STREAM, {OrderCancelled: handler})],
        block_ms=1,
        **kwargs,
    )
    consumer.ensure_groups()
    return consumer


def _pending(redis) -> int:
    return redis.xpending(ORDERS_STREAM, "inventory")["pending"]


def test_handler_receives_published_event_and_message_is_acked(redis) -> None:
    received: list[Event] = []
    consumer = _consumer(redis, received.append)
    RedisStreamPublisher(redis).publish(ORDERS_STREAM, _event())

    assert consumer.poll() == 1
    assert [e.order_id for e in received] == ["ord_1"]
    assert _pending(redis) == 0


def test_failed_message_is_retried_then_dead_lettered(redis) -> None:
    calls: list[str] = []

    def failing(event: Event) -> None:
        calls.append(event.event_id)
        raise RuntimeError("database locked")

    consumer = _consumer(redis, failing, max_attempts=2, retry_after_ms=0)
    RedisStreamPublisher(redis).publish(ORDERS_STREAM, _event())

    consumer.poll()
    assert _pending(redis) == 1
    consumer.poll()
    consumer.poll()

    assert len(calls) == 2
    assert _pending(redis) == 0
    dead = redis.xrange(f"{ORDERS_STREAM}.dead")
    assert len(dead) == 1
    assert dead[0][1]["reason"] == "max attempts exceeded"


def test_unknown_event_type_is_skipped(redis) -> None:
    received: list[Event] = []
    consumer = _consumer(redis, received.append)
    redis.xadd(ORDERS_STREAM, {"event_type": "order.gift_wrapped", "event_id": "x", "data": "{}"})

    consumer.poll()
    assert received == []
    assert _pending(redis) == 0


def test_undecodable_event_goes_to_dead_letter_stream(redis) -> None:
    consumer = _consumer(redis, lambda event: None)
    fields = encode(_event())
    fields["data"] = '{"order_id": 5}'
    redis.xadd(ORDERS_STREAM, fields)

    consumer.poll()
    assert _pending(redis) == 0
    assert len(redis.xrange(f"{ORDERS_STREAM}.dead")) == 1


def test_ensure_groups_is_repeatable(redis) -> None:
    consumer = _consumer(redis, lambda event: None)
    consumer.ensure_groups()
