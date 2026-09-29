import logging
from typing import Protocol

from redis import Redis

from shop_platform.events import Event, encode

logger = logging.getLogger(__name__)


class EventPublisher(Protocol):
    def publish(self, stream: str, event: Event) -> None: ...


def redis_from_url(url: str) -> Redis:
    """Redis client configured the way the messaging code expects (string responses)."""
    return Redis.from_url(url, decode_responses=True)


class RedisStreamPublisher:
    def __init__(self, redis: Redis, *, maxlen: int = 100_000) -> None:
        self._redis = redis
        self._maxlen = maxlen

    def publish(self, stream: str, event: Event) -> None:
        message_id = self._redis.xadd(stream, encode(event), maxlen=self._maxlen, approximate=True)
        logger.info(
            "event published",
            extra={
                "stream": stream,
                "event_type": event.EVENT_TYPE,
                "event_id": event.event_id,
                "message_id": message_id,
            },
        )
