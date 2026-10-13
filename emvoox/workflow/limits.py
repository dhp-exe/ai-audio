"""Per-provider cap on concurrent vendor requests, shared by every scene that renders in parallel."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from emvoox.providers.tts import default_concurrency


class ProviderLimiter:
    """``with limiter.slot("gemini"): ...`` blocks while the provider is at its limit. ``peak`` records the most
    requests that ever ran at once per provider, so a test (or a run log) can prove the cap held."""

    def __init__(self, limit_for: Callable[[str], int] = default_concurrency):
        self._limit_for = limit_for
        self._lock = threading.Lock()
        self._slots: dict[str, threading.BoundedSemaphore] = {}
        self._active: dict[str, int] = {}
        self.peak: dict[str, int] = {}

    def limit(self, provider: str) -> int:
        return max(1, self._limit_for(provider))

    @contextmanager
    def slot(self, provider: str) -> Iterator[None]:
        with self._lock:
            sem = self._slots.setdefault(provider, threading.BoundedSemaphore(self.limit(provider)))
        with sem:
            with self._lock:
                self._active[provider] = self._active.get(provider, 0) + 1
                self.peak[provider] = max(self.peak.get(provider, 0), self._active[provider])
            try:
                yield
            finally:
                with self._lock:
                    self._active[provider] -= 1
