"""
lucid_tuner_protocol.adapter — drop LTP onto any agent team.

Turns the ltp-core primitives (DropClient, TuningProtocol, TruthGate, Reading)
into a one-line wrap: a framework-agnostic ``LTPSession`` plus native adapters
for the main harnesses. It adds no new protocol logic.

    from lucid_tuner_protocol.adapter import LTPSession, tuned

    session = LTPSession(complete=my_llm_call, cadence="daily", anchor="drop", role="analyst")
    reply = await session.respond(messages, user_message)   # tuned + gated

    client = tuned(OpenAI(...), cadence="session", role="steward")   # OpenAI-compatible

Framework adapters (import the submodule, or use the lazy names below):

    from lucid_tuner_protocol.adapter.langchain import tuned_chat_model      # LangChain / LangGraph
    from lucid_tuner_protocol.adapter.crewai import tuned_crew_llm           # CrewAI
    from lucid_tuner_protocol.adapter.openai_agents import tuned_agents_model  # OpenAI Agents SDK

Their heavy dependencies are optional extras (``lucid-tuner-protocol[langchain]``,
``[crewai]``, ``[agents]``) and are imported only when you use them.
"""

from .observability import GateEvent, ReadingRecord, Sinks
from .openai_shim import tuned
from .session import LTPSession
from .store import InMemoryStore, Store
from .tuning import (
    ANCHOR_DROP,
    ANCHOR_OFFLINE,
    ANCHOR_PRIVATE,
    TuningResolver,
    TuningState,
    resolve_archetype_coaching,
)

__all__ = [
    "LTPSession",
    "tuned",
    "TuningResolver",
    "TuningState",
    "resolve_archetype_coaching",
    "Store",
    "InMemoryStore",
    "ReadingRecord",
    "GateEvent",
    "Sinks",
    "ANCHOR_DROP",
    "ANCHOR_OFFLINE",
    "ANCHOR_PRIVATE",
    # lazy framework factories (see __getattr__)
    "tuned_chat_model",
    "tuned_crew_llm",
    "tuned_agents_model",
    "tuned_agents_client",
]

# Lazy access to framework factories so importing this package never pulls in
# langchain / crewai / openai-agents. Accessing the name imports its submodule.
_LAZY = {
    "tuned_chat_model": ("langchain", "tuned_chat_model"),
    "tuned_crew_llm": ("crewai", "tuned_crew_llm"),
    "tuned_agents_model": ("openai_agents", "tuned_agents_model"),
    "tuned_agents_client": ("openai_agents", "tuned_agents_client"),
}


def __getattr__(name):
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    mod = importlib.import_module(f"{__name__}.{target[0]}")
    return getattr(mod, target[1])
