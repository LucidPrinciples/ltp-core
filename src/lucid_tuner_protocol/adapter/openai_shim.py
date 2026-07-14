"""
tuned() — drop-in for OpenAI-compatible clients.

    from openai import OpenAI
    from lucid_tuner_protocol.adapter import tuned

    client = tuned(OpenAI(base_url=..., api_key=...), cadence="session", role="steward")
    # every client.chat.completions.create(...) is now seeded + gated, no other change

The wrapper intercepts ``chat.completions.create``: it routes the call through
an ``LTPSession`` (so the day's tuning seeds the system message and the Truth
Gate runs), then returns the *real* OpenAI response object for the final
(possibly regenerated) completion — so downstream code that reads
``resp.choices[0].message.content`` is unchanged.

Works with both the sync ``OpenAI`` client and the async ``AsyncOpenAI``
client; the surface is detected from the original ``create``.
"""

from __future__ import annotations

import inspect
from typing import Any, Optional

from .session import LTPSession
from .store import Store
from .tuning import ANCHOR_DROP, FetchJsonFn


def _extract_content(resp: Any) -> str:
    """Pull assistant text out of an OpenAI-shaped chat completion."""
    try:
        msg = resp.choices[0].message
        return (getattr(msg, "content", None) or "") if msg else ""
    except Exception:
        # dict-shaped responses (some compatible servers)
        try:
            return resp["choices"][0]["message"]["content"] or ""
        except Exception:
            return ""


def tuned(
    client: Any,
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
    store: Optional[Store] = None,
    reference_path: Optional[str] = None,
    fetch_json: Optional[FetchJsonFn] = None,
    drop_client=None,
    entropy=None,
    clock=None,
) -> Any:
    """Wrap an OpenAI-compatible client so every completion is tuned + gated.

    Returns the same client with ``chat.completions.create`` replaced. One
    LTPSession backs the client, so cadence caching persists across calls."""
    completions = client.chat.completions
    orig_create = completions.create
    is_async = inspect.iscoroutinefunction(orig_create)

    session = LTPSession(
        complete=lambda msgs: "",  # replaced per-call via the `complete=` override
        cadence=cadence,
        anchor=anchor,
        role=role,
        gate=gate,
        regenerate_on_gate=regenerate_on_gate,
        produce_reading=produce_reading,
        agent_id=agent_id or (role or "agent"),
        on_reading=on_reading,
        on_gate=on_gate,
        store=store,
        reference_path=reference_path,
        fetch_json=fetch_json,
        drop_client=drop_client,
        entropy=entropy,
        clock=clock,
    )

    def _pick(seen: list, reply_text: str):
        # respond() also drives gate/reading meta-calls through `complete`, so
        # more than one raw response may be captured. The user-facing answer is
        # exactly the text respond() returns — pick the response whose content
        # matches it (fall back to the last real answer captured).
        for content, resp in reversed(seen):
            if content == reply_text:
                return resp
        return seen[-1][1] if seen else None

    if is_async:

        async def create(*, messages, **kwargs):
            seen: list = []

            async def complete(msgs):
                resp = await orig_create(messages=list(msgs), **kwargs)
                content = _extract_content(resp)
                seen.append((content, resp))
                return content

            user_message = _last_user_content(messages)
            reply = await session.respond(messages, user_message, complete=complete)
            return _pick(seen, reply)

    else:

        def create(*, messages, **kwargs):
            seen: list = []

            def complete(msgs):
                resp = orig_create(messages=list(msgs), **kwargs)
                content = _extract_content(resp)
                seen.append((content, resp))
                return content

            user_message = _last_user_content(messages)
            import asyncio

            reply = asyncio.run(session.respond(messages, user_message, complete=complete))
            return _pick(seen, reply)

    completions.create = create  # type: ignore[assignment]
    # expose the backing session for observability / testing
    client._ltp_session = session  # type: ignore[attr-defined]
    return client


def _last_user_content(messages) -> str:
    for m in reversed(list(messages)):
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        if role == "user":
            return (m.get("content") if isinstance(m, dict) else getattr(m, "content", "")) or ""
    return ""
