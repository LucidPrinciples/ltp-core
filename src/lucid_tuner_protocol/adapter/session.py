"""
LTPSession — wrap any completion callable so every response is tuned + gated.

    session = LTPSession(
        complete=my_llm_call,     # (messages) -> text, sync or async
        cadence="daily",          # per_call | session | daily
        anchor="drop",            # drop | offline | private
        role="analyst",
        gate=True,
        on_reading=log_reading,
        on_gate=log_gate,
    )
    reply = await session.respond(messages, user_message)   # tuned + gated

Responsibilities, in order, per completion:
  1. Resolve the day's tuning once per cadence (Drop first, offline fallback).
  2. Seed ``as_context()`` into the system message.
  3. Call the wrapped model.
  4. Run the Truth Gate; regenerate exactly once if it fires.
  5. Emit the Reading (per cadence) and the gate event (per call).

Both async (``respond``) and sync (``respond_sync``) surfaces are provided.
"""

from __future__ import annotations

import asyncio
import datetime
import inspect
from typing import Awaitable, Callable, Optional, Sequence, Union

from .. import TruthGate

from .observability import GateEvent, ReadingRecord, Sinks
from .store import InMemoryStore, Store
from .tuning import (
    ANCHOR_DROP,
    FetchJsonFn,
    TuningResolver,
    TuningState,
)

Message = dict  # {"role": str, "content": str}
Messages = Sequence[Message]
# The wrapped agent completion: (messages) -> text, sync or async.
CompleteFn = Callable[[Messages], Union[str, Awaitable[str]]]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _default_clock() -> str:
    return datetime.date.today().isoformat()


def _last_user(messages: Messages) -> str:
    for m in reversed(list(messages)):
        if m.get("role") == "user":
            return m.get("content", "") or ""
    return ""


def _seed_system(messages: Messages, block: str) -> list:
    """Prepend ``block`` to the system message (merging if one exists)."""
    if not block:
        return list(messages)
    out = [dict(m) for m in messages]
    for m in out:
        if m.get("role") == "system":
            existing = m.get("content", "") or ""
            m["content"] = f"{block}\n\n{existing}".rstrip() if existing else block
            return out
    return [{"role": "system", "content": block}, *out]


class LTPSession:
    def __init__(
        self,
        complete: CompleteFn,
        *,
        cadence: str = "daily",
        anchor: str = ANCHOR_DROP,
        role: Optional[str] = None,
        gate: bool = True,
        regenerate_on_gate: bool = True,
        produce_reading: bool = True,
        agent_id: str = "agent",
        on_reading=None,
        on_gate=None,
        store: Optional[Store] = None,
        reference_path: Optional[str] = None,
        fetch_json: Optional[FetchJsonFn] = None,
        drop_client=None,
        entropy: Optional[Callable] = None,
        clock: Optional[Callable[[], str]] = None,
    ):
        if cadence not in ("per_call", "session", "daily"):
            raise ValueError(f"unknown cadence: {cadence!r}")
        self._complete = complete
        self.cadence = cadence
        self.role = role
        self.agent_id = agent_id
        self._gate = gate
        self._regenerate = regenerate_on_gate
        self._produce_reading = produce_reading
        self._store: Store = store if store is not None else InMemoryStore()
        self._clock = clock or _default_clock
        self._sinks = Sinks(on_reading=on_reading, on_gate=on_gate)
        self._resolver = TuningResolver(
            anchor=anchor,
            reference_path=reference_path,
            drop_client=drop_client,
            fetch_json=fetch_json,
            entropy=entropy,
        )
        self._session_tuning: Optional[TuningState] = None
        self._cycle = 0

    # ── tuning resolution + cadence caching ──────────────────────────────

    def _cache_key(self, date: str) -> str:
        if self.cadence == "daily":
            return f"{self.agent_id}:{date}"
        return f"{self.agent_id}:session"

    async def tuning(self, complete: Optional[CompleteFn] = None) -> TuningState:
        """Resolve (or reuse) the tuning for the current cadence window.

        Emits a ReadingRecord + records it to the store on each *fresh*
        resolution (once per day for daily, once per session for session,
        every call for per_call)."""
        date = self._clock()
        bridged = self._bridge(complete or self._complete)

        if self.cadence == "session" and self._session_tuning is not None:
            return self._session_tuning
        if self.cadence == "daily":
            cached = self._store.get_tuning(self._cache_key(date))
            if cached is not None:
                self._session_tuning = cached
                return cached

        history = self._store.history(self.agent_id)
        state = await self._resolver.resolve(
            date=date,
            complete=bridged,
            history=history,
            produce_reading=self._produce_reading,
            role=self.role or "",
            agent_id=self.agent_id,
        )

        # Record recency + emit the reading on a fresh resolution.
        self._store.note_selection(
            self.agent_id, state.frequency, state.principle, state.tuning_key
        )
        if state.reading is not None:
            self._cycle += 1
            record = ReadingRecord.from_reading(
                state.reading,
                agent_id=self.agent_id,
                date=date,
                cycle=self._cycle,
                source=state.source,
                role=self.role,
                archetype=state.archetype,
                frequency=state.frequency,
                principle=state.principle,
            )
            self._store.record_reading(self.agent_id, record)
            self._sinks.emit_reading(record)

        if self.cadence in ("session", "daily"):
            self._store.put_tuning(self._cache_key(date), state)
            self._session_tuning = state
        return state

    # ── the wrapped completion ───────────────────────────────────────────

    async def respond(
        self,
        messages: Messages,
        user_message: Optional[str] = None,
        *,
        complete: Optional[CompleteFn] = None,
    ) -> str:
        """Tuned + gated completion. ``complete`` overrides the wrapped model
        for this call (used by the OpenAI shim to carry per-call kwargs)."""
        model = complete or self._complete
        state = await self.tuning(complete=model)

        seeded = _seed_system(messages, state.context)
        reply = await _maybe_await(model(seeded))
        reply = reply or ""

        if not self._gate:
            return reply

        last = user_message if user_message is not None else _last_user(messages)
        result = await TruthGate(
            complete=self._bridge(model), anchor=state.anchor
        ).check(reply, last)

        regenerated = False
        if result.fired and self._regenerate:
            regen_msgs = _seed_system(seeded, result.anchor_context)
            reply = await _maybe_await(model(regen_msgs)) or reply
            regenerated = True

        self._sinks.emit_gate(
            GateEvent(
                agent_id=self.agent_id,
                date=state.date,
                cycle=self._cycle,
                fired=result.fired,
                regenerated=regenerated,
                passed=(not result.fired) or regenerated,
                role=self.role,
                description=result.description,
                truth_available=result.truth_available,
            )
        )
        return reply

    def respond_sync(
        self, messages: Messages, user_message: Optional[str] = None
    ) -> str:
        """Synchronous surface. Not for use inside a running event loop."""
        return asyncio.run(self.respond(messages, user_message))

    # ── helpers ──────────────────────────────────────────────────────────

    def _bridge(self, complete: CompleteFn):
        """Adapt an agent completion ``(messages) -> text`` into ltp-core's
        ``(system, prompt) -> text`` contract used by the gate and reading."""

        def _sp_complete(system: str, prompt: str):
            return complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ]
            )

        return _sp_complete

    def readings(self) -> list:
        """All ReadingRecords collected for this agent (from the store)."""
        return self._store.readings(self.agent_id)
