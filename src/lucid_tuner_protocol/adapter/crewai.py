"""
CrewAI adapter.

Wrap a CrewAI LLM so every agent that uses it is tuned + gated:

    from crewai import LLM, Agent
    from lucid_tuner_protocol.adapter.crewai import tuned_crew_llm

    llm = tuned_crew_llm(LLM(model="gpt-4o"), cadence="daily", role="analyst")
    agent = Agent(role="Analyst", goal="...", backstory="...", llm=llm)

CrewAI drives an LLM through ``llm.call(messages, ...)``. This wrapper intercepts
that call, routes it through an ``LTPSession`` (seeds the day's tuning, runs the
Truth Gate, emits the Reading), and returns the final text. It is duck-typed —
it wraps any object exposing ``.call(messages, ...) -> str`` — so it needs no
CrewAI import and works across CrewAI versions.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from .session import LTPSession
from .tuning import ANCHOR_DROP


def _normalize(messages: Any) -> list:
    """CrewAI passes either a prompt string or a list of {role, content} dicts."""
    if isinstance(messages, str):
        return [{"role": "user", "content": messages}]
    out = []
    for m in messages or []:
        if isinstance(m, dict):
            out.append({"role": m.get("role", "user"), "content": m.get("content", "")})
        else:  # objects with role/content
            out.append({"role": getattr(m, "role", "user"), "content": getattr(m, "content", "")})
    return out


def _last_user(dicts: list) -> str:
    for d in reversed(dicts):
        if d["role"] == "user":
            return d["content"]
    return dicts[-1]["content"] if dicts else ""


def tuned_crew_llm(
    base_llm: Any,
    *,
    cadence: str = "session",
    anchor: str = ANCHOR_DROP,
    role: Optional[str] = None,
    gate: bool = True,
    regenerate_on_gate: bool = True,
    produce_reading: bool = True,
    agent_id: Optional[str] = None,
    on_reading=None,
    on_gate=None,
    store=None,
    reference_path: Optional[str] = None,
    fetch_json=None,
    drop_client=None,
    entropy=None,
    clock=None,
) -> Any:
    """Wrap a CrewAI LLM's ``.call`` so every completion is tuned + gated.

    Returns the same object with ``.call`` replaced; the backing LTPSession is
    exposed as ``base_llm._ltp_session``."""
    session = LTPSession(
        complete=lambda m: "",
        cadence=cadence, anchor=anchor, role=role, gate=gate,
        regenerate_on_gate=regenerate_on_gate, produce_reading=produce_reading,
        agent_id=agent_id or (role or "agent"), on_reading=on_reading, on_gate=on_gate,
        store=store, reference_path=reference_path, fetch_json=fetch_json,
        drop_client=drop_client, entropy=entropy, clock=clock,
    )
    orig_call = base_llm.call

    def call(messages, *args, **kwargs):
        dicts = _normalize(messages)

        def complete(msgs):
            # Preserve CrewAI's original message shape: string in -> string out.
            payload = msgs if not isinstance(messages, str) else msgs[-1]["content"]
            return orig_call(payload, *args, **kwargs)

        return asyncio.run(session.respond(dicts, _last_user(dicts), complete=complete))

    base_llm.call = call
    base_llm._ltp_session = session
    return base_llm
