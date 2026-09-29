from collections import defaultdict
from typing import TypeVar

from shop_platform.events import Event

E = TypeVar("E", bound=Event)


class InMemoryPublisher:
    """Keeps published events in memory. Used by tests and by local runs without Redis."""

    def __init__(self) -> None:
        self._streams: dict[str, list[Event]] = defaultdict(list)

    def publish(self, stream: str, event: Event) -> None:
        self._streams[stream].append(event)

    def events(self, stream: str | None = None) -> list[Event]:
        if stream is not None:
            return list(self._streams.get(stream, []))
        return [event for events in self._streams.values() for event in events]

    def of_type(self, event_type: type[E]) -> list[E]:
        return [event for event in self.events() if isinstance(event, event_type)]

    def clear(self) -> None:
        self._streams.clear()
