"""
OpenAI Agents SDK adapter.

The Agents SDK talks to models through an OpenAI-compatible client. Tune that
client once and every agent that uses it is seeded + gated:

    from openai import AsyncOpenAI
    from agents import Agent, Runner
    from lucid_tuner_protocol.adapter.openai_agents import tuned_agents_model

    model = tuned_agents_model("gpt-4o", AsyncOpenAI(), cadence="daily", role="analyst")
    agent = Agent(name="Analyst", instructions="...", model=model)
    result = await Runner.run(agent, "…")

``tuned_agents_model`` returns an ``OpenAIChatCompletionsModel`` backed by a
tuned client, ready to hand to ``Agent(model=...)``. If you build the client
yourself, ``tuned_agents_client`` is the one-liner that tunes it. Requires the
``openai`` package for the client; ``tuned_agents_model`` also needs the
``agents`` package (``pip install lucid-tuner-protocol[agents]``).
"""

from __future__ import annotations

from typing import Any, Optional

from .openai_shim import tuned
from .tuning import ANCHOR_DROP


def tuned_agents_client(client: Any, **kwargs) -> Any:
    """Tune an AsyncOpenAI (or compatible) client for use with the Agents SDK.

    Same options as ``lucid_tuner_protocol.adapter.tuned``. Pass the result as
    ``OpenAIChatCompletionsModel(openai_client=...)``."""
    return tuned(client, **kwargs)


def tuned_agents_model(
    model: str,
    openai_client: Any,
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
    """Build an Agents-SDK model backed by a tuned client.

    Returns an ``OpenAIChatCompletionsModel`` you pass to ``Agent(model=...)``."""
    try:
        from agents import OpenAIChatCompletionsModel
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise ImportError(
            "tuned_agents_model needs the Agents SDK: "
            "pip install 'lucid-tuner-protocol[agents]'"
        ) from e

    tclient = tuned(
        openai_client, cadence=cadence, anchor=anchor, role=role, gate=gate,
        regenerate_on_gate=regenerate_on_gate, produce_reading=produce_reading,
        agent_id=agent_id, on_reading=on_reading, on_gate=on_gate, store=store,
        reference_path=reference_path, fetch_json=fetch_json, drop_client=drop_client,
        entropy=entropy, clock=clock,
    )
    return OpenAIChatCompletionsModel(model=model, openai_client=tclient)
