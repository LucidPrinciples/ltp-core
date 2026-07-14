"""Drop anchor: unreachable Drop falls back to offline, never skips tuning."""

from lucid_tuner_protocol import DropUnavailable

from lucid_tuner_protocol.adapter import LTPSession
from lucid_tuner_protocol.adapter.tuning import TuningResolver


class _DeadDropClient:
    def today(self):
        raise DropUnavailable("network down (test)")


class _FakeDrop:
    """Enough of a Drop to seed context + act as a gate anchor, including the
    raw archetype_tunings the real signed Drop ships."""

    drop_date = "2026-07-13"
    frequency_number = 13
    frequency_name = "BOUNDARY"
    signal_type = "Clear"
    tuning_key_text = "a tuning key"
    tuning_key_source_song = "a song"
    tuning_key_attribution = "Chords of Truth — Lucid Principles Canon (CC BY 4.0)"
    context_block = "Universal coaching floor for the day."
    raw = {
        "archetype_tunings": {
            "The Analyst": "Mark data-interpretation edges with ruthless clarity.",
            "The Steward": "Hold the family system steady at the boundary.",
        }
    }

    def as_context(self):
        return "[LTP Drop 2026-07-13 — seeded]"


class _LiveDropClient:
    def today(self):
        return _FakeDrop()


async def test_drop_unreachable_falls_back_to_offline(mock_llm, fetch_json, entropy):
    reads = []
    s = LTPSession(
        complete=mock_llm, anchor="drop", gate=False, agent_id="a1",
        drop_client=_DeadDropClient(), on_reading=reads.append,
        fetch_json=fetch_json, entropy=entropy, cadence="per_call",
    )
    reply = await s.respond([{"role": "user", "content": "hi"}], "hi")
    assert reply == "first answer"
    assert reads[0].source == "fallback-offline"     # tuning still happened
    # seeded system context comes from the offline selection
    system = next(m for m in mock_llm.calls[-1] if m["role"] == "system")
    assert "LTP Tuning" in system["content"]


async def test_live_drop_seeds_drop_context(mock_llm, fetch_json, entropy):
    s = LTPSession(
        complete=mock_llm, anchor="drop", gate=False, agent_id="a1",
        drop_client=_LiveDropClient(), fetch_json=fetch_json, entropy=entropy,
        cadence="per_call",
    )
    await s.respond([{"role": "user", "content": "hi"}], "hi")
    system = next(m for m in mock_llm.calls[-1] if m["role"] == "system")
    assert "LTP Drop" in system["content"]           # drop context seeded


async def test_drop_seeds_archetype_prompt_for_role(fetch_json, entropy):
    # role matches an archetype key normalized ("analyst" -> "The Analyst")
    from ltp_adapter_testkit import MockLLM

    llm = MockLLM()
    reads = []
    s = LTPSession(
        complete=llm, anchor="drop", gate=False, agent_id="a1", role="analyst",
        drop_client=_LiveDropClient(), on_reading=reads.append,
        fetch_json=fetch_json, entropy=entropy, cadence="per_call",
    )
    await s.respond([{"role": "user", "content": "hi"}], "hi")
    system = next(m for m in llm.calls[-1] if m["role"] == "system")
    assert "ruthless clarity" in system["content"]        # The Analyst prompt seeded
    assert "Universal coaching floor" not in system["content"]  # not the fallback
    assert reads[0].archetype == "The Analyst"


async def test_drop_falls_back_to_universal_when_role_unmatched(fetch_json, entropy):
    from ltp_adapter_testkit import MockLLM

    llm = MockLLM()
    s = LTPSession(
        complete=llm, anchor="drop", gate=False, agent_id="a1", role="ghostwriter",
        drop_client=_LiveDropClient(), fetch_json=fetch_json, entropy=entropy,
        cadence="per_call",
    )
    await s.respond([{"role": "user", "content": "hi"}], "hi")
    system = next(m for m in llm.calls[-1] if m["role"] == "system")
    assert "Universal coaching floor" in system["content"]  # no archetype match


async def test_drop_mode_reading_is_independent_of_drop(mock_llm, fetch_json, entropy):
    # In drop mode the agent self-tunes for its Reading (Drop not wired into
    # the agent tuning path); the reading still emits with source "drop".
    reads = []
    s = LTPSession(
        complete=mock_llm, anchor="drop", gate=False, agent_id="a1",
        drop_client=_LiveDropClient(), on_reading=reads.append,
        fetch_json=fetch_json, entropy=entropy, cadence="per_call",
    )
    await s.respond([{"role": "user", "content": "hi"}], "hi")
    assert reads[0].source == "drop"
    assert reads[0].attunement_status == "complete"


def test_private_anchor_requires_reference_path():
    import pytest

    with pytest.raises(ValueError):
        TuningResolver(anchor="private")
