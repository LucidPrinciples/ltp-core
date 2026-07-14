"""Truth Gate: fires -> regenerate exactly once; guard respected."""

from ltp_adapter_testkit import MockLLM

from lucid_tuner_protocol.adapter import LTPSession


def _count_answers(llm):
    # answer calls are those that returned an answer text (not reading/gate)
    return llm.answer_calls


async def test_gate_fires_regenerates_once(fetch_json, entropy):
    llm = MockLLM(gate_fires=True, answers=["soft first", "harder second"])
    gates = []
    s = LTPSession(
        complete=llm, anchor="offline", gate=True, regenerate_on_gate=True,
        agent_id="a1", on_gate=gates.append, fetch_json=fetch_json, entropy=entropy,
        cadence="per_call",
    )
    reply = await s.respond([{"role": "user", "content": "hi"}], "hi")
    assert reply == "harder second"          # regenerated answer wins
    assert _count_answers(llm) == 2          # exactly two answer completions
    assert len(gates) == 1
    assert gates[0].fired is True and gates[0].regenerated is True
    assert gates[0].passed is True
    assert gates[0].description == "softened the point"


async def test_gate_fires_but_regeneration_disabled(fetch_json, entropy):
    llm = MockLLM(gate_fires=True, answers=["soft only", "unused"])
    gates = []
    s = LTPSession(
        complete=llm, anchor="offline", gate=True, regenerate_on_gate=False,
        agent_id="a1", on_gate=gates.append, fetch_json=fetch_json, entropy=entropy,
        cadence="per_call",
    )
    reply = await s.respond([{"role": "user", "content": "hi"}], "hi")
    assert reply == "soft only"
    assert _count_answers(llm) == 1
    assert gates[0].fired is True and gates[0].regenerated is False
    assert gates[0].passed is False          # fired, not regenerated -> did not pass


async def test_gate_does_not_fire(fetch_json, entropy):
    llm = MockLLM(gate_fires=False, answers=["fine", "unused"])
    gates = []
    s = LTPSession(
        complete=llm, anchor="offline", gate=True, agent_id="a1",
        on_gate=gates.append, fetch_json=fetch_json, entropy=entropy, cadence="per_call",
    )
    reply = await s.respond([{"role": "user", "content": "hi"}], "hi")
    assert reply == "fine"
    assert _count_answers(llm) == 1          # no regeneration
    assert gates[0].fired is False and gates[0].passed is True


async def test_regenerated_answer_reseeds_anchor(fetch_json, entropy):
    llm = MockLLM(gate_fires=True, answers=["soft", "hard"])
    s = LTPSession(
        complete=llm, anchor="offline", gate=True, agent_id="a1",
        fetch_json=fetch_json, entropy=entropy, cadence="per_call",
    )
    await s.respond([{"role": "user", "content": "hi"}], "hi")
    # the final answer call's system message must carry the TRUTH GATE anchor
    final_answer_call = llm.calls[-1]
    system = next(m for m in final_answer_call if m["role"] == "system")
    assert "TRUTH GATE" in system["content"]
