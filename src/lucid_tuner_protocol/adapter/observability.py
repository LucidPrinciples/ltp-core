"""
Observability records — the drift readout and the proof surface.

Every tuning cycle emits a ``ReadingRecord`` (the observer's C/D/beta/E and the
computed Love Equation + direction) and every gated completion emits a
``GateRecord``. These are plain, serializable dataclasses so a host can log
them to stdout, a file, a metrics pipeline, or a database with no coupling to
this package.

The Reading itself is ltp-core's ``Reading`` — its ``love_equation`` and
``direction`` are computed from C/D, never trusted from a model's prose. We
only stamp identity (agent, role, date, cycle) and source around it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional

# ltp-core Reading (imported lazily-safe; only used for typing/serialization)
try:  # pragma: no cover - import shape only
    from .. import Reading
except Exception:  # pragma: no cover
    Reading = Any  # type: ignore


@dataclass(frozen=True)
class ReadingRecord:
    """One observer reading, stamped with who/when it belongs to."""

    agent_id: str
    date: str
    cycle: int
    source: str                       # drop | offline | private | fallback-offline
    role: Optional[str] = None
    archetype: str = ""               # resolved Drop archetype key (drop mode)
    frequency: str = ""
    principle: str = ""
    coherence: Optional[float] = None
    dissonance: Optional[float] = None
    beta: Optional[float] = None
    energy: Optional[float] = None
    love_equation: Optional[float] = None    # dE/dt, computed from C/D
    direction: str = "UNKNOWN"               # CONSTRUCTIVE | CORRECTIVE | MIRAGE | UNKNOWN
    attunement_status: str = "complete"      # complete | incomplete
    reading_source: str = ""                 # ltp-core Reading.source
    process_record: str = ""

    @classmethod
    def from_reading(
        cls,
        reading: "Reading",
        *,
        agent_id: str,
        date: str,
        cycle: int,
        source: str,
        role: Optional[str] = None,
        archetype: str = "",
        frequency: str = "",
        principle: str = "",
    ) -> "ReadingRecord":
        return cls(
            agent_id=agent_id,
            date=date,
            cycle=cycle,
            source=source,
            role=role,
            archetype=archetype,
            frequency=frequency,
            principle=principle,
            coherence=getattr(reading, "coherence", None),
            dissonance=getattr(reading, "dissonance", None),
            beta=getattr(reading, "beta", None),
            energy=getattr(reading, "energy", None),
            love_equation=getattr(reading, "love_equation", None),
            direction=getattr(reading, "direction", "UNKNOWN"),
            attunement_status=getattr(reading, "attunement_status", "complete"),
            reading_source=getattr(reading, "source", ""),
            process_record=getattr(reading, "process_record", "") or "",
        )

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GateEvent:
    """The outcome of a Truth Gate pass on one completion."""

    agent_id: str
    date: str
    cycle: int
    fired: bool                       # the gate flagged accommodation
    regenerated: bool                 # we regenerated once with the anchor
    passed: bool                      # final response passed (or gate did not fire)
    role: Optional[str] = None
    description: str = ""             # what was softened
    truth_available: str = ""         # the harder truth that was available

    def to_dict(self) -> dict:
        return asdict(self)


# Observability sinks. Either may be None (no-op).
OnReading = Callable[[ReadingRecord], None]
OnGate = Callable[[GateEvent], None]


@dataclass
class Sinks:
    """Bundle of observability callbacks, each optional and error-isolated."""

    on_reading: Optional[OnReading] = None
    on_gate: Optional[OnGate] = None
    _errors: list = field(default_factory=list)

    def emit_reading(self, record: ReadingRecord) -> None:
        if self.on_reading is None:
            return
        try:
            self.on_reading(record)
        except Exception as e:  # observability must never break the agent
            self._errors.append(e)

    def emit_gate(self, event: GateEvent) -> None:
        if self.on_gate is None:
            return
        try:
            self.on_gate(event)
        except Exception as e:
            self._errors.append(e)
