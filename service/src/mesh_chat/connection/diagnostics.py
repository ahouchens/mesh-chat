"""Bounded, payload-free diagnostics. No peer identifiers leave this module."""

from collections import Counter, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Record:
    sequence: int
    event: str
    previous: str
    current: str
    reason: str
    effects: tuple[str, ...]


class Diagnostics:
    def __init__(self, limit: int):
        self._records = deque(maxlen=limit)
        self._counts = Counter()
        self._sequence = 0

    def record(self, previous, event, result):
        self._sequence += 1
        self._counts[result.reason] += 1
        self._records.append(Record(self._sequence, type(event).__name__,
                             previous.reason, result.state.reason, result.reason,
                             tuple(type(effect).__name__ for effect in result.effects)))

    def snapshot(self):
        return tuple(self._records), dict(self._counts)
