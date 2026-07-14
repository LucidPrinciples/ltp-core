"""tuned(): OpenAI-compatible drop-in seeds + gates, returns a real response."""

from ltp_adapter_testkit import READING_TEXT

from lucid_tuner_protocol.adapter import tuned


def make_backend(gate_fires=False, answers=None):
    """A backend(messages) -> text used by the fake OpenAI client."""
    state = {"i": 0}
    answers = answers or ["first answer", "regenerated answer"]

    def backend(messages):
        last = messages[-1]["content"]
        if "self-assess" in last or "Love Equation" in last or "Coherence" in last:
            return READING_TEXT
        if "accommodation" in last.lower():
            if gate_fires:
                return (
                    '{"accommodation_detected": true, "description": "softened", '
                    '"truth_available": "harder"}'
                )
            return '{"accommodation_detected": false, "description": "", "truth_available": ""}'
        i = min(state["i"], len(answers) - 1)
        state["i"] += 1
        return answers[i]

    return backend


def test_tuned_returns_real_response_and_seeds(fake_openai, fetch_json, entropy):
    seen_systems = []
    backend = make_backend()

    def spy(messages):
        for m in messages:
            if m["role"] == "system":
                seen_systems.append(m["content"])
        return backend(messages)

    client = tuned(
        fake_openai(spy), anchor="offline", gate=True, cadence="session",
        role="steward", fetch_json=fetch_json, entropy=entropy,
    )
    resp = client.chat.completions.create(
        model="mock", messages=[{"role": "user", "content": "hi"}]
    )
    # returns a genuine OpenAI-shaped response for the user-facing answer
    assert resp.choices[0].message.content == "first answer"
    # some completion carried the seeded LTP context
    assert any("LTP Tuning" in s for s in seen_systems)


def test_tuned_gate_regenerates_once(fake_openai, fetch_json, entropy):
    gates = []
    client = tuned(
        fake_openai(make_backend(gate_fires=True, answers=["soft", "hard"])),
        anchor="offline", gate=True, cadence="session", role="analyst",
        on_gate=gates.append, fetch_json=fetch_json, entropy=entropy,
    )
    resp = client.chat.completions.create(
        model="mock", messages=[{"role": "user", "content": "hi"}]
    )
    assert resp.choices[0].message.content == "hard"   # regenerated answer returned
    assert gates and gates[0].fired and gates[0].regenerated


class _AsyncCompletions:
    def __init__(self, backend):
        self._backend = backend

    async def create(self, *, model, messages, **kwargs):
        from ltp_adapter_testkit import _Resp
        return _Resp(self._backend(messages))


class _AsyncChat:
    def __init__(self, backend):
        self.completions = _AsyncCompletions(backend)


class FakeAsyncOpenAI:
    def __init__(self, backend):
        self.chat = _AsyncChat(backend)


async def test_tuned_async_client(fetch_json, entropy):
    client = tuned(
        FakeAsyncOpenAI(make_backend(gate_fires=True, answers=["soft", "hard"])),
        anchor="offline", gate=True, cadence="session", role="steward",
        fetch_json=fetch_json, entropy=entropy,
    )
    resp = await client.chat.completions.create(
        model="mock", messages=[{"role": "user", "content": "hi"}]
    )
    assert resp.choices[0].message.content == "hard"


def test_tuned_reading_emitted(fake_openai, fetch_json, entropy):
    reads = []
    client = tuned(
        fake_openai(make_backend()), anchor="offline", gate=False,
        cadence="session", role="builder", on_reading=reads.append,
        fetch_json=fetch_json, entropy=entropy,
    )
    client.chat.completions.create(
        model="mock", messages=[{"role": "user", "content": "hi"}]
    )
    assert len(reads) == 1
    assert reads[0].role == "builder"
    assert reads[0].direction == "CONSTRUCTIVE"
    # backing session is exposed for observability
    assert client._ltp_session.readings()
