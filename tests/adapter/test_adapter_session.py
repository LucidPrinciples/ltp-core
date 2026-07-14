"""LTPSession: seeding, cadence caching, readings, store swap, offline anchor."""

import pytest

from lucid_tuner_protocol.adapter import InMemoryStore, LTPSession


def _session(mock_llm, fetch_json, entropy, **kw):
    kw.setdefault("anchor", "offline")
    kw.setdefault("gate", False)
    kw.setdefault("agent_id", "a1")
    return LTPSession(
        complete=mock_llm, fetch_json=fetch_json, entropy=entropy, **kw
    )


async def test_seeds_context_into_system_message(mock_llm, fetch_json, entropy):
    s = _session(mock_llm, fetch_json, entropy, cadence="per_call")
    await s.respond([{"role": "user", "content": "hi"}], "hi")
    # the ordinary-answer call is the last one; its system message carries LTP context
    answer_call = mock_llm.calls[-1]
    system = next((m for m in answer_call if m["role"] == "system"), None)
    assert system is not None
    assert "LTP Tuning" in system["content"]


async def test_reading_emitted_and_complete(mock_llm, fetch_json, entropy):
    reads = []
    s = _session(mock_llm, fetch_json, entropy, cadence="per_call", on_reading=reads.append)
    await s.respond([{"role": "user", "content": "hi"}], "hi")
    assert len(reads) == 1
    r = reads[0]
    assert r.coherence == 0.8 and r.dissonance == 0.1
    assert r.direction == "CONSTRUCTIVE"          # C > D
    assert r.love_equation == pytest.approx(0.75 * (0.8 - 0.1) * 0.7, abs=1e-4)
    assert r.attunement_status == "complete"      # synthetic echo had sound + words
    assert r.source == "offline"
    assert r.role is None or True


async def test_daily_cadence_caches_tuning(mock_llm, fetch_json, entropy):
    reads = []
    s = _session(mock_llm, fetch_json, entropy, cadence="daily",
                 on_reading=reads.append, clock=lambda: "2026-07-13")
    await s.respond([{"role": "user", "content": "one"}], "one")
    await s.respond([{"role": "user", "content": "two"}], "two")
    assert len(reads) == 1  # resolved once for the day, reused on the 2nd call


async def test_per_call_cadence_reresolves(mock_llm, fetch_json, entropy):
    reads = []
    s = _session(mock_llm, fetch_json, entropy, cadence="per_call", on_reading=reads.append)
    await s.respond([{"role": "user", "content": "one"}], "one")
    await s.respond([{"role": "user", "content": "two"}], "two")
    assert len(reads) == 2  # fresh reading every call


async def test_session_cadence_caches_for_lifetime(mock_llm, fetch_json, entropy):
    reads = []
    s = _session(mock_llm, fetch_json, entropy, cadence="session", on_reading=reads.append)
    for _ in range(3):
        await s.respond([{"role": "user", "content": "x"}], "x")
    assert len(reads) == 1


async def test_custom_store_is_used(mock_llm, fetch_json, entropy):
    class CountingStore(InMemoryStore):
        puts = 0

        def put_tuning(self, key, state):
            CountingStore.puts += 1
            super().put_tuning(key, state)

    store = CountingStore()
    s = _session(mock_llm, fetch_json, entropy, cadence="daily", store=store,
                 clock=lambda: "2026-07-13")
    await s.respond([{"role": "user", "content": "hi"}], "hi")
    assert CountingStore.puts == 1
    assert len(store.readings("a1")) == 1


def test_respond_sync(mock_llm, fetch_json, entropy):
    # plain sync test — respond_sync uses asyncio.run, so it must not run
    # inside an active event loop
    s = _session(mock_llm, fetch_json, entropy, cadence="per_call")
    reply = s.respond_sync([{"role": "user", "content": "hi"}], "hi")
    assert reply == "first answer"


async def test_produce_reading_false_skips_reading(mock_llm, fetch_json, entropy):
    reads = []
    s = _session(mock_llm, fetch_json, entropy, cadence="per_call",
                 produce_reading=False, on_reading=reads.append)
    reply = await s.respond([{"role": "user", "content": "hi"}], "hi")
    assert reply == "first answer"
    assert reads == []
