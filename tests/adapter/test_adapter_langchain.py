"""LangChain / LangGraph adapter — real langchain-core BaseChatModel."""

import pytest

pytest.importorskip("langchain_core")

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatResult  # noqa: E402

from ltp_adapter_testkit import READING_TEXT  # noqa: E402
from lucid_tuner_protocol.adapter.langchain import tuned_chat_model  # noqa: E402


class FakeChat(BaseChatModel):
    """A minimal chat model whose reply depends on the message content."""

    gate_fires: bool = False
    calls: list = []
    _counter: dict = {}

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self):
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1].content
        self.calls.append([(m.type, m.content) for m in messages])
        if "self-assess" in last or "Love Equation" in last or "Coherence" in last:
            text = READING_TEXT
        elif "accommodation" in last.lower():
            text = (
                '{"accommodation_detected": true, "description": "soft", "truth_available": "hard"}'
                if self.gate_fires
                else '{"accommodation_detected": false, "description": "", "truth_available": ""}'
            )
        else:
            n = self._counter.get("n", 0)
            self._counter["n"] = n + 1
            text = "hard" if (self.gate_fires and n >= 1) else ("soft" if self.gate_fires else "plain answer")
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def test_tuned_chat_model_sync(fetch_json, entropy):
    reads = []
    inner = FakeChat()
    inner.calls = []
    inner._counter = {}
    llm = tuned_chat_model(inner, anchor="offline", gate=False, role="analyst",
                           on_reading=reads.append, fetch_json=fetch_json,
                           entropy=entropy, cadence="session")
    out = llm.invoke([HumanMessage(content="hi")])
    assert out.content == "plain answer"
    assert reads and reads[0].role == "analyst"
    # a seeded system message reached the inner model
    assert any(any(t == "system" and "LTP Tuning" in c for t, c in call) for call in inner.calls)


async def test_tuned_chat_model_async(fetch_json, entropy):
    inner = FakeChat()
    inner.calls = []
    inner._counter = {}
    llm = tuned_chat_model(inner, anchor="offline", gate=False, role="analyst",
                           fetch_json=fetch_json, entropy=entropy, cadence="session")
    out = await llm.ainvoke([HumanMessage(content="hi")])
    assert out.content == "plain answer"


def test_tuned_chat_model_gate_regenerates(fetch_json, entropy):
    gates = []
    inner = FakeChat()
    inner.gate_fires = True
    inner.calls = []
    inner._counter = {}
    llm = tuned_chat_model(inner, anchor="offline", gate=True, role="steward",
                           on_gate=gates.append, fetch_json=fetch_json,
                           entropy=entropy, cadence="session")
    out = llm.invoke([HumanMessage(content="hi")])
    assert out.content == "hard"          # regenerated
    assert gates and gates[0].fired and gates[0].regenerated
