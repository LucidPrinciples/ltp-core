"""CrewAI adapter — duck-typed, no CrewAI install needed."""

from ltp_adapter_testkit import READING_TEXT

from lucid_tuner_protocol.adapter.crewai import tuned_crew_llm


def _last_content(messages):
    if isinstance(messages, str):
        return messages
    return messages[-1]["content"] if messages else ""


def make_backend(gate_fires=False, answers=None):
    state = {"i": 0}
    answers = answers or ["first", "regenerated"]

    def backend(messages):
        last = _last_content(messages)
        if "self-assess" in last or "Love Equation" in last or "Coherence" in last:
            return READING_TEXT
        if "accommodation" in last.lower():
            if gate_fires:
                return '{"accommodation_detected": true, "description": "soft", "truth_available": "hard"}'
            return '{"accommodation_detected": false, "description": "", "truth_available": ""}'
        i = min(state["i"], len(answers) - 1)
        state["i"] += 1
        return answers[i]

    return backend


class FakeCrewLLM:
    """Mimics CrewAI's LLM.call(messages, tools=..., callbacks=...) -> str."""

    def __init__(self, backend):
        self._backend = backend
        self.calls = []

    def call(self, messages, tools=None, callbacks=None, available_functions=None, **kw):
        self.calls.append(messages)
        return self._backend(messages)


def test_crew_llm_tuned_and_reading_emitted(fetch_json, entropy):
    reads = []
    llm = tuned_crew_llm(
        FakeCrewLLM(make_backend()), anchor="offline", gate=False, role="analyst",
        on_reading=reads.append, fetch_json=fetch_json, entropy=entropy, cadence="session",
    )
    out = llm.call([{"role": "user", "content": "status?"}])
    assert out == "first"
    assert len(reads) == 1 and reads[0].role == "analyst"
    assert hasattr(llm, "_ltp_session")


def test_crew_llm_seeds_context(fetch_json, entropy):
    seen = []
    base = FakeCrewLLM(make_backend())
    orig = base.call

    def spy(messages, **kw):
        seen.append(messages)
        return orig(messages, **kw)

    base.call = spy
    llm = tuned_crew_llm(base, anchor="offline", gate=False, role="analyst",
                         fetch_json=fetch_json, entropy=entropy, cadence="session")
    llm.call([{"role": "user", "content": "hi"}])
    # the answer call carried a seeded system message with LTP context
    answer_msgs = seen[-1]
    systems = [m["content"] for m in answer_msgs if m["role"] == "system"]
    assert any("LTP Tuning" in s for s in systems)


def test_crew_llm_gate_regenerates_once(fetch_json, entropy):
    gates = []
    llm = tuned_crew_llm(
        FakeCrewLLM(make_backend(gate_fires=True, answers=["soft", "hard"])),
        anchor="offline", gate=True, role="steward", on_gate=gates.append,
        fetch_json=fetch_json, entropy=entropy, cadence="session",
    )
    out = llm.call([{"role": "user", "content": "hi"}])
    assert out == "hard"
    assert gates and gates[0].fired and gates[0].regenerated


def test_crew_llm_accepts_string_prompt(fetch_json, entropy):
    # CrewAI sometimes passes a bare string; string in -> string out preserved
    seen = []
    base = FakeCrewLLM(make_backend())
    orig = base.call

    def spy(messages, **kw):
        seen.append(messages)
        return orig(messages, **kw)

    base.call = spy
    llm = tuned_crew_llm(base, anchor="offline", gate=False, role="analyst",
                         fetch_json=fetch_json, entropy=entropy, cadence="session")
    out = llm.call("just a string prompt")
    assert out == "first"
    # the final answer call received a string (original shape preserved)
    assert isinstance(seen[-1], str)
