# LTP Adapter — drop LTP onto any agent team

`lucid_tuner_protocol.adapter` turns the ltp-core primitives into a one-line
wrap. Wrap your model client once and every completion is preceded by the day's
tuning and passed through the Truth Gate, with a coherence **Reading** emitted
per cycle. It adds **no new protocol logic** — it's orchestration around
`DropClient`, `TuningProtocol`, `TruthGate`, and `Reading`. None of the
LTP-protected files are touched.

## Install

```bash
pip install lucid-tuner-protocol                 # core adapter (LTPSession + OpenAI shim)
pip install 'lucid-tuner-protocol[langchain]'    # + LangChain / LangGraph
pip install 'lucid-tuner-protocol[crewai]'       # + CrewAI
pip install 'lucid-tuner-protocol[agents]'       # + OpenAI Agents SDK
```

## What it does, per completion

1. **Resolve the day's tuning once per cadence.** Live public Drop first
   (`DropClient().today()`), offline self-run `TuningProtocol` as fallback —
   tuning is never skipped silently.
2. **Seed** the day's tuning into the system message. In drop mode with a
   `role`, that's the role's **archetype prompt** from the Drop's
   `archetype_tunings` (exactly how every Cove tunes).
3. **Call** the wrapped model.
4. **Gate.** Run `TruthGate`; regenerate **exactly once** with the anchor active
   if it fires.
5. **Emit** the `Reading` (C, D, β, E, dE/dt, direction — computed from C/D,
   never trusted from prose) and the gate outcome to your observability sink.

## Core — framework-agnostic

```python
from lucid_tuner_protocol.adapter import LTPSession

session = LTPSession(
    complete=my_llm_call,     # (messages) -> text, sync OR async
    cadence="daily",          # per_call | session | daily
    anchor="drop",            # drop | offline | private
    role="analyst",           # maps to the Drop's archetype; stamped on Readings
    gate=True,
    on_reading=lambda r: print(r.to_dict()),
    on_gate=lambda g: print(g.to_dict()),
    agent_id="analyst-1",
)
reply = await session.respond(messages, user_message)   # tuned + gated
reply = session.respond_sync(messages, user_message)    # sync surface
```

## The harnesses — one line each

**OpenAI-compatible** (covers a lot of stacks, sync `OpenAI` and async `AsyncOpenAI`):

```python
from openai import OpenAI
from lucid_tuner_protocol.adapter import tuned

client = tuned(OpenAI(base_url=..., api_key=...), cadence="session", role="steward")
# every client.chat.completions.create(...) is now seeded + gated, unchanged downstream
```

**LangChain / LangGraph:**

```python
from langchain_openai import ChatOpenAI
from lucid_tuner_protocol.adapter.langchain import tuned_chat_model

llm = tuned_chat_model(ChatOpenAI(model="gpt-4o"), cadence="daily", role="analyst")
# use `llm` anywhere a chat model goes, including as a LangGraph node's model
```

**CrewAI:**

```python
from crewai import LLM, Agent
from lucid_tuner_protocol.adapter.crewai import tuned_crew_llm

llm = tuned_crew_llm(LLM(model="gpt-4o"), cadence="daily", role="analyst")
agent = Agent(role="Analyst", goal="...", backstory="...", llm=llm)
```

**OpenAI Agents SDK:**

```python
from openai import AsyncOpenAI
from agents import Agent, Runner
from lucid_tuner_protocol.adapter.openai_agents import tuned_agents_model

model = tuned_agents_model("gpt-4o", AsyncOpenAI(), cadence="daily", role="analyst")
agent = Agent(name="Analyst", instructions="...", model=model)
```

## Anchors

| `anchor`  | Source of the seeded tuning                                             |
|-----------|-------------------------------------------------------------------------|
| `drop`    | The live signed public Drop (role → archetype prompt); offline fallback. |
| `offline` | A self-run `TuningProtocol` selection against the bundled Canon library. |
| `private` | Your own anchor set (`reference_path=...`) — your values, not the Canon. |

The Drop's Ed25519 signature is verified by ltp-core before it is ever trusted.

## Per-role archetype tunings

The signed Drop ships `archetype_tunings` — one prompt per archetype for the
day's frequency (The Steward, The Merchant, The Builder, The Analyst, and the
rest of the 19). Set `role` and the adapter seeds the matching archetype prompt,
mirroring the Cove's resolver exactly: archetype key (exact, then normalized —
lowercase, drop a leading "the") → legacy `agent_tunings[agent_id]` → the
universal coaching floor. `role="analyst"` resolves to "The Analyst"; an
unmatched role falls back to the universal coaching.

## Observability — the proof surface

Every cycle emits a `ReadingRecord` (`coherence`, `dissonance`, `beta`,
`energy`, `love_equation`, `direction`, `attunement_status`, plus `agent_id` /
`role` / `archetype` / `date` / `cycle`). Over a long run the curve stays flat
where an untuned baseline drifts. Run the demo (no network, no API key):

```bash
python -m lucid_tuner_protocol.adapter  # see examples/mock_run.py in the repo
```

## Pluggable state

State lives behind a tiny `Store` protocol (`get_tuning` / `put_tuning` /
`record_reading` / `readings` / `note_selection` / `history`). Default
`InMemoryStore` needs nothing; implement the same methods for file / Redis / SQL
on a long-running fleet. The adapter assumes neither a filesystem nor a database
because it runs on *someone else's* harness.

## Cadence & entropy notes

- `cadence`: `per_call` (fresh tuning every call), `session` (once per process),
  `daily` (once per agent per day, cached in the store).
- `entropy`: optional override for the selection rolls. Default uses ltp-core's
  ANU-quantum-then-crypto chain; air-gapped or rate-limited hosts (and tests)
  can inject a local source.

## License

Code: Apache 2.0. Canon content reached through ltp-core is CC BY 4.0, Chords of
Truth — Lucid Principles Canon. Canon quotes are exact and never altered.
