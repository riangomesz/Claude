"""Relógio injetável: o motor nunca lê a hora diretamente, para leases, backoff e demonstrações reproduzíveis."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone


class SystemClock:
    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class FakeClock:
    """Relógio manual e thread-safe (testes e demonstração). `sleep` só avança o tempo."""

    def __init__(self, start: float = 1_800_000_000.0):
        self._t = float(start)
        self._lock = threading.Lock()

    def now(self) -> float:
        with self._lock:
            return self._t

    def advance(self, seconds: float) -> float:
        with self._lock:
            self._t += float(seconds)
            return self._t

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.advance(seconds)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="microseconds")
