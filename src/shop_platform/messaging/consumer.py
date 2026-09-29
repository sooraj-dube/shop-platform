import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pydantic import ValidationError
from redis import Redis
from redis.exceptions import ResponseError

from shop_platform.events import Event, UnknownEventType, decode

logger = logging.getLogger(__name__)

Handler = Callable[[Event], None]


@dataclass(frozen=True)
class Subscription:
    stream: str
    handlers: Mapping[type[Event], Handler] = field(default_factory=dict)


class StreamConsumer:
    """Reads one consumer group across several streams and hands events to handlers.

    A message is acknowledged once its handler returns. When a handler raises, the
    message stays pending and is claimed again after ``retry_after_ms``. A message
    delivered more than ``max_attempts`` times is copied to ``<stream>.dead`` and
    acknowledged. Event types with no handler are acknowledged and skipped.
    """

    def __init__(
        self,
        redis: Redis,
        *,
        group: str,
        consumer: str,
        subscriptions: list[Subscription],
        max_attempts: int = 5,
        retry_after_ms: int = 30_000,
        block_ms: int = 5_000,
        batch_size: int = 50,
    ) -> None:
        if not subscriptions:
            raise ValueError("at least one subscription is required")
        self._redis = redis
        self._group = group
        self._consumer = consumer
        self._handlers = {sub.stream: dict(sub.handlers) for sub in subscriptions}
        self._max_attempts = max_attempts
        self._retry_after_ms = retry_after_ms
        self._block_ms = block_ms
        self._batch_size = batch_size

    def ensure_groups(self) -> None:
        for stream in self._handlers:
            try:
                self._redis.xgroup_create(stream, self._group, id="0", mkstream=True)
            except ResponseError as exc:
                if "BUSYGROUP" not in str(exc):
                    raise

    def poll(self) -> int:
        """Process one batch: first messages due for retry, then new ones. Returns the count."""
        handled = self._retry_pending()
        response = self._redis.xreadgroup(
            self._group,
            self._consumer,
            {stream: ">" for stream in self._handlers},
            count=self._batch_size,
            block=self._block_ms,
        )
        for stream, messages in response or []:
            for message_id, fields in messages:
                self._process(stream, message_id, fields)
                handled += 1
        return handled

    def run(self, stop: threading.Event) -> None:
        self.ensure_groups()
        logger.info(
            "consumer started", extra={"group": self._group, "streams": list(self._handlers)}
        )
        while not stop.is_set():
            try:
                self.poll()
            except Exception:
                logger.exception("consumer poll failed", extra={"group": self._group})
                stop.wait(1.0)
        logger.info("consumer stopped", extra={"group": self._group})

    def _retry_pending(self) -> int:
        handled = 0
        for stream in self._handlers:
            _, messages, _ = self._redis.xautoclaim(
                stream,
                self._group,
                self._consumer,
                min_idle_time=self._retry_after_ms,
                start_id="0-0",
                count=self._batch_size,
            )
            for message_id, fields in messages:
                if self._deliveries(stream, message_id) > self._max_attempts:
                    self._dead_letter(stream, message_id, fields, "max attempts exceeded")
                else:
                    self._process(stream, message_id, fields)
                handled += 1
        return handled

    def _process(self, stream: str, message_id: str, fields: Mapping[str, str]) -> None:
        context = {"stream": stream, "message_id": message_id, "group": self._group}
        try:
            event = decode(fields)
        except UnknownEventType:
            logger.info(
                "skipping unknown event type",
                extra={**context, "event_type": fields.get("event_type")},
            )
            self._redis.xack(stream, self._group, message_id)
            return
        except (ValidationError, KeyError) as exc:
            logger.error("undecodable event", extra={**context, "error": str(exc)})
            self._dead_letter(stream, message_id, fields, f"undecodable: {exc}")
            return

        handler = self._handlers[stream].get(type(event))
        if handler is None:
            self._redis.xack(stream, self._group, message_id)
            return
        try:
            handler(event)
        except Exception:
            logger.exception(
                "event handler failed; will retry",
                extra={**context, "event_type": event.EVENT_TYPE, "event_id": event.event_id},
            )
            return
        self._redis.xack(stream, self._group, message_id)

    def _deliveries(self, stream: str, message_id: str) -> int:
        pending = self._redis.xpending_range(
            stream, self._group, min=message_id, max=message_id, count=1
        )
        return int(pending[0]["times_delivered"]) if pending else 0

    def _dead_letter(
        self, stream: str, message_id: str, fields: Mapping[str, str], reason: str
    ) -> None:
        self._redis.xadd(
            f"{stream}.dead",
            {**fields, "source_message_id": message_id, "group": self._group, "reason": reason},
        )
        self._redis.xack(stream, self._group, message_id)
        logger.error(
            "event dead-lettered",
            extra={"stream": stream, "message_id": message_id, "reason": reason},
        )
