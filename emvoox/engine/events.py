"""In-process event bus. Every state change of a run is published as a ``PipelineEvent``; subscribers
persist the run state, append the event log the UI tails, and can forward to V1RON OS later."""

from __future__ import annotations

import threading
from collections.abc import Callable

from emvoox.contracts.run import PipelineEvent

Subscriber = Callable[[PipelineEvent], None]


class EventBus:
    def __init__(self, start: int = 0) -> None:
        """``start`` = events this run already published (a run continued by another process keeps counting)."""
        self._subs: list[Subscriber] = []
        self._seq = start
        self._lock = threading.Lock()
        self.history: list[PipelineEvent] = []

    def subscribe(self, fn: Subscriber) -> None:
        self._subs.append(fn)

    def publish(self, event: PipelineEvent) -> PipelineEvent:
        with self._lock:
            self._seq += 1
            event.seq = self._seq
            self.history.append(event)
        for fn in list(self._subs):
            try:
                fn(event)
            except Exception:  # noqa: BLE001 - a broken subscriber must not stop production
                pass
        return event
