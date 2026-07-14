"""OpenAI Agents SDK adapter.

The primary route tunes the OpenAI-compatible client the SDK uses; that path is
covered here with a fake client. tuned_agents_model is exercised only when the
`agents` package is installed."""

import pytest

from ltp_adapter_testkit import READING_TEXT
from lucid_tuner_protocol.adapter.openai_agents import tuned_agents_client, tuned_agents_model


def make_backend(answers=None):
    state = {"i": 0}
    answers = answers or ["first answer", "regenerated answer"]

    def backend(messages):
        last = messages[-1]["content"]
        if "self-assess" in last or "Love Equation" in last or "Coherence" in last:
            return READING_TEXT
        if "accommodation" in last.lower():
            return '{"accommodation_detected": false, "description": "", "truth_available": ""}'
        i = min(state["i"], len(answers) - 1)
        state["i"] += 1
        return answers[i]

    return backend


def test_tuned_agents_client_tunes_the_client(fake_openai, fetch_json, entropy):
    reads = []
    client = tuned_agents_client(
        fake_openai(make_backend()), anchor="offline", gate=False, cadence="session",
        role="analyst", on_reading=reads.append, fetch_json=fetch_json, entropy=entropy,
    )
    resp = client.chat.completions.create(
        model="mock", messages=[{"role": "user", "content": "hi"}]
    )
    assert resp.choices[0].message.content == "first answer"
    assert reads and reads[0].role == "analyst"
    assert hasattr(client, "_ltp_session")


def test_tuned_agents_model_requires_sdk(fake_openai, fetch_json, entropy):
    pytest.importorskip("agents")
    model = tuned_agents_model(
        "gpt-4o", fake_openai(make_backend()), anchor="offline", role="analyst",
        fetch_json=fetch_json, entropy=entropy,
    )
    # returns an OpenAIChatCompletionsModel bound to the tuned client
    assert model is not None
