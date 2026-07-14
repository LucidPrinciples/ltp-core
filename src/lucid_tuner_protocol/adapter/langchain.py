"""
LangChain / LangGraph adapter.

Wrap any LangChain ``BaseChatModel`` so every call it makes is tuned + gated:

    from langchain_openai import ChatOpenAI
    from lucid_tuner_protocol.adapter.langchain import tuned_chat_model

    llm = tuned_chat_model(ChatOpenAI(model="gpt-4o"), cadence="daily", role="analyst")
    # use `llm` anywhere a chat model goes — including as a LangGraph node's model

The wrapper is a real ``BaseChatModel`` subclass, so it drops into chains,
agents, and LangGraph nodes unchanged. Requires ``langchain-core``
(``pip install lucid-tuner-protocol[langchain]``).
"""

from __future__ import annotations

import asyncio
from typing import List, Optional

from .session import LTPSession
from .tuning import ANCHOR_DROP

try:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
    from langchain_core.outputs import ChatGeneration, ChatResult
except ImportError as e:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "The LangChain adapter needs langchain-core: "
        "pip install 'lucid-tuner-protocol[langchain]'"
    ) from e


_ROLE_FOR_TYPE = {"system": "system", "human": "user", "ai": "assistant"}
_MSG_FOR_ROLE = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}


def _to_dicts(messages: List[BaseMessage]) -> list:
    out = []
    for m in messages:
        out.append({"role": _ROLE_FOR_TYPE.get(getattr(m, "type", "human"), "user"),
                    "content": m.content})
    return out


def _to_lc(dicts: list) -> list:
    return [_MSG_FOR_ROLE.get(d["role"], HumanMessage)(content=d["content"]) for d in dicts]


def _last_user(dicts: list) -> str:
    for d in reversed(dicts):
        if d["role"] == "user":
            return d["content"]
    return ""


class TunedChatModel(BaseChatModel):
    """A BaseChatModel that routes generations through an LTPSession."""

    inner: BaseChatModel
    ltp: LTPSession

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return f"ltp-tuned::{getattr(self.inner, '_llm_type', 'chat')}"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        dicts = _to_dicts(messages)

        def complete(msgs):
            resp = self.inner.invoke(_to_lc(msgs), stop=stop, **kwargs)
            return getattr(resp, "content", "") or ""

        text = asyncio.run(self.ltp.respond(dicts, _last_user(dicts), complete=complete))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        dicts = _to_dicts(messages)

        async def complete(msgs):
            resp = await self.inner.ainvoke(_to_lc(msgs), stop=stop, **kwargs)
            return getattr(resp, "content", "") or ""

        text = await self.ltp.respond(dicts, _last_user(dicts), complete=complete)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def tuned_chat_model(
    llm: BaseChatModel,
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
) -> TunedChatModel:
    """Wrap a LangChain chat model so every generation is tuned + gated."""
    session = LTPSession(
        complete=lambda m: "",  # overridden per call via respond(complete=...)
        cadence=cadence, anchor=anchor, role=role, gate=gate,
        regenerate_on_gate=regenerate_on_gate, produce_reading=produce_reading,
        agent_id=agent_id or (role or "agent"), on_reading=on_reading, on_gate=on_gate,
        store=store, reference_path=reference_path, fetch_json=fetch_json,
        drop_client=drop_client, entropy=entropy, clock=clock,
    )
    return TunedChatModel(inner=llm, ltp=session)
