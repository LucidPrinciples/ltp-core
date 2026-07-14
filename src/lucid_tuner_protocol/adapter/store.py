"""
State store — where each agent's resolved tuning and reading history live.

Phase 1 ships an in-memory default. The ``Store`` protocol is deliberately
tiny so a host can drop in a file, Redis, or SQL backend for a long-running
fleet without touching the session logic. This is the seam the operator plugs
into precisely because the adapter is meant to run on *someone else's* harness,
where we cannot assume a filesystem or a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional, Protocol, runtime_checkable

from .. import History

if TYPE_CHECKING:  # avoid a runtime import cycle
    from .tuning import TuningState
    from .observability import ReadingRecord


@runtime_checkable
class Store(Protocol):
    """Persistence seam for tuning cache + reading history + recency."""

    def get_tuning(self, key: str) -> "Optional[TuningState]": ...

    def put_tuning(self, key: str, state: "TuningState") -> None: ...

    def record_reading(self, agent_id: str, record: "ReadingRecord") -> None: ...

    def readings(self, agent_id: str) -> "list[ReadingRecord]": ...

    def note_selection(
        self, agent_id: str, frequency: str, principle: str, tuning_key: str
    ) -> None: ...

    def history(self, agent_id: str, window: int = 5) -> History: ...


@dataclass
class InMemoryStore:
    """Default store. Everything lives in process memory, keyed by agent.

    Not shared across processes and gone on restart — which is exactly right
    for the mock example and unit tests, and a clean template for a real
    backend (implement the same six methods)."""

    _tunings: dict = field(default_factory=dict)
    _readings: dict = field(default_factory=dict)
    _recent_freq: dict = field(default_factory=dict)
    _recent_principle: dict = field(default_factory=dict)
    _recent_key: dict = field(default_factory=dict)
    _principle_counts: dict = field(default_factory=dict)

    def get_tuning(self, key: str) -> "Optional[TuningState]":
        return self._tunings.get(key)

    def put_tuning(self, key: str, state: "TuningState") -> None:
        self._tunings[key] = state

    def record_reading(self, agent_id: str, record: "ReadingRecord") -> None:
        self._readings.setdefault(agent_id, []).append(record)

    def readings(self, agent_id: str) -> "list[ReadingRecord]":
        return list(self._readings.get(agent_id, []))

    def note_selection(
        self, agent_id: str, frequency: str, principle: str, tuning_key: str
    ) -> None:
        if frequency:
            self._recent_freq.setdefault(agent_id, []).append(frequency)
        if principle:
            self._recent_principle.setdefault(agent_id, []).append(principle)
            counts = self._principle_counts.setdefault(agent_id, {})
            counts[principle] = counts.get(principle, 0) + 1
        if tuning_key:
            self._recent_key.setdefault(agent_id, []).append(tuning_key)

    def history(self, agent_id: str, window: int = 5) -> History:
        return History(
            recent_frequencies=self._recent_freq.get(agent_id, [])[-window:],
            recent_principles=self._recent_principle.get(agent_id, [])[-window:],
            recent_tuning_keys=self._recent_key.get(agent_id, [])[-window:],
            principle_usage_counts=dict(self._principle_counts.get(agent_id, {})),
        )
