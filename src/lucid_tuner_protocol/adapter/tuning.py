"""
Tuning resolution — resolve the day's tuning once per cadence.

Two things come out of a resolution and they are kept separate on purpose:

  1. ``context`` — the injectable block that gets seeded into the system
     message on every completion. Its source is the operator's chosen anchor:
     the live public Drop, an offline self-run selection, or a private anchor
     set.
  2. ``reading`` — the observer's own Reading, produced when the agent
     actually processes a tuning via ``TuningProtocol.tune_full``. This is the
     coherence readout, computed (never trusted) from C/D.

Failure posture (spec): if the Drop is unreachable we fall back to an offline
self-run tuning rather than skipping tuning silently. We never regenerate more
than once on a gate fire (that guard lives in the session).
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Union

from .. import (
    DropClient,
    DropUnavailable,
    History,
    Reading,
    TuningProtocol,
    select_tuning,
)

# complete(system, prompt) -> str | awaitable[str]   (ltp-core's contract)
SystemPromptComplete = Callable[[str, str], Union[str, Awaitable[str]]]
# fetch_json(url) -> dict | awaitable[dict]           (echo analysis fetcher)
FetchJsonFn = Callable[[str], Union[dict, Awaitable[dict]]]

ANCHOR_DROP = "drop"
ANCHOR_OFFLINE = "offline"
ANCHOR_PRIVATE = "private"


@dataclass(frozen=True)
class TuningState:
    """A resolved tuning for one agent on one cadence window."""

    context: str                 # injected into the system message every call
    anchor: Any                  # Drop or Selection — the TruthGate day anchor
    source: str                  # drop | offline | private | fallback-offline
    date: str
    frequency: str = ""
    principle: str = ""
    tuning_key: str = ""
    reading: Optional[Reading] = None
    note: str = ""
    archetype: str = ""          # resolved archetype key (drop mode, when matched)
    coaching_source: str = ""    # archetype | legacy-agent | universal


def _norm_archetype(s: str) -> str:
    """Normalize an archetype label for matching: lowercase, drop a leading
    'the'. Mirrors the Cove's coaching resolver exactly."""
    s = (s or "").strip().lower()
    if s.startswith("the "):
        s = s[4:]
    return s.strip()


def resolve_archetype_coaching(
    drop: Any, role: str = "", agent_id: str = ""
) -> tuple[str, str, str]:
    """Resolve the day's coaching for one agent from a Drop's archetype prompts.

    Returns (coaching_text, resolved_archetype_key, coaching_source). Mirrors the
    Cove's ``resolve_coaching`` order: archetype exact -> archetype normalized ->
    legacy agent_tunings[agent_id] -> universal context_block. The public typed
    Drop does not expose ``archetype_tunings``, so we read ``drop.raw``."""
    raw = getattr(drop, "raw", {}) or {}
    archetype_tunings = raw.get("archetype_tunings", {}) or {}
    agent_tunings = raw.get("agent_tunings", {}) or {}
    universal = getattr(drop, "context_block", "") or ""

    if role and archetype_tunings:
        if archetype_tunings.get(role):
            return archetype_tunings[role], role, "archetype"
        nr = _norm_archetype(role)
        for k, v in archetype_tunings.items():
            if _norm_archetype(k) == nr and v:
                return v, k, "archetype"
    if agent_id and agent_tunings.get(agent_id):
        return agent_tunings[agent_id], "", "legacy-agent"
    return universal, "", "universal"


def _compose_drop_context(drop: Any, coaching: str) -> str:
    """The injectable block for a Drop, mirroring ltp-core's ``Drop.as_context``
    but with the coaching swapped for the agent's archetype prompt."""
    return (
        f"[LTP Drop {getattr(drop, 'drop_date', '')} — "
        f"Frequency {getattr(drop, 'frequency_number', '')}/13: "
        f"{getattr(drop, 'frequency_name', '')} ({getattr(drop, 'signal_type', '')})]\n"
        f'Tuning Key: "{getattr(drop, "tuning_key_text", "")}"\n'
        f"— {getattr(drop, 'tuning_key_attribution', '')}\n\n"
        f"{coaching}"
    )


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _anchor_fields(anchor: Any) -> tuple[str, str, str]:
    """Pull (frequency, principle, tuning_key) off a Drop or a Selection."""
    if anchor is None:
        return "", "", ""
    # Selection has frequency/principle/tuning_key; Drop uses *_name/_text.
    frequency = getattr(anchor, "frequency", "") or getattr(anchor, "frequency_name", "")
    principle = getattr(anchor, "principle", "") or getattr(
        anchor, "tuning_key_source_song", ""
    )
    tuning_key = getattr(anchor, "tuning_key", "") or getattr(anchor, "tuning_key_text", "")
    return frequency, principle, tuning_key


class TuningResolver:
    """Resolves a ``TuningState`` for an anchor mode. Holds no per-agent state
    (that lives in the Store); it only owns the Drop/protocol clients."""

    def __init__(
        self,
        anchor: str = ANCHOR_DROP,
        *,
        reference_path: Optional[str] = None,
        drop_client: Optional[DropClient] = None,
        fetch_json: Optional[FetchJsonFn] = None,
        entropy: Optional[Callable] = None,
    ):
        if anchor not in (ANCHOR_DROP, ANCHOR_OFFLINE, ANCHOR_PRIVATE):
            raise ValueError(f"unknown anchor mode: {anchor!r}")
        if anchor == ANCHOR_PRIVATE and reference_path is None:
            raise ValueError('anchor="private" requires reference_path')
        self.anchor_mode = anchor
        self.reference_path = reference_path
        self._drop_client = drop_client
        self._fetch_json = fetch_json
        # Optional entropy override for the selection rolls. Default (None) uses
        # ltp-core's ANU-quantum-then-crypto chain. Hosts that are air-gapped or
        # rate-limited can inject a local source; tests inject a fast one.
        self._entropy = entropy
        # A local canon/custom protocol backs offline anchoring AND the agent's
        # own self-tuning (the Reading), independent of the public Drop.
        if anchor == ANCHOR_PRIVATE:
            self._protocol = TuningProtocol(anchor="custom", reference_path=reference_path)
        else:
            self._protocol = TuningProtocol(anchor="canon")

    async def resolve(
        self,
        *,
        date: str,
        complete: Optional[SystemPromptComplete],
        history: Optional[History] = None,
        produce_reading: bool = True,
        role: str = "",
        agent_id: str = "",
    ) -> TuningState:
        # 1. Resolve the seed context + gate anchor. `selection` is the offline
        #    Selection (None when the anchor is the public Drop). In drop mode the
        #    seed is the agent's ARCHETYPE prompt from the Drop (role-keyed).
        context, anchor, source, note, selection, archetype, coaching_source = (
            await self._resolve_anchor(history, role, agent_id)
        )

        # 2. Produce the agent's own Reading (optional). In offline/private the
        #    agent reads the same tuning it is anchored to. In drop mode it
        #    self-tunes independently — the public Drop is NOT wired into the
        #    agent's tuning path (locked LTP rule); the Drop is only the seed.
        reading: Optional[Reading] = None
        if produce_reading and complete is not None:
            sel = selection if selection is not None else await self._select(history)
            experience = await self._protocol.attune(sel, fetch_json=self._fetch_json)
            reading = await self._protocol.derive(experience, complete)

        freq, principle, key = _anchor_fields(anchor)
        return TuningState(
            context=context,
            anchor=anchor,
            source=source,
            date=date,
            frequency=freq,
            principle=principle,
            tuning_key=key,
            reading=reading,
            note=note,
            archetype=archetype,
            coaching_source=coaching_source,
        )

    async def _select(self, history):
        """One selection chain, honoring an injected entropy source."""
        if self._entropy is not None:
            return await select_tuning(
                reference=self._protocol.reference, history=history, entropy=self._entropy
            )
        return await self._protocol.tune(history)

    async def _resolve_anchor(self, history, role="", agent_id=""):
        if self.anchor_mode == ANCHOR_DROP:
            try:
                drop = await asyncio.to_thread(self._today)
                # Seed the agent's ARCHETYPE prompt from the Drop (role-keyed),
                # falling back to legacy agent key, then the universal coaching —
                # exactly how every Cove tunes from the public Drop.
                coaching, archetype, csource = resolve_archetype_coaching(
                    drop, role=role, agent_id=agent_id
                )
                return (
                    _compose_drop_context(drop, coaching),
                    drop,
                    "drop",
                    "",
                    None,
                    archetype,
                    csource,
                )
            except DropUnavailable as e:
                # Never skip tuning silently — fall back to offline.
                sel = await self._select(history)
                return (
                    self._protocol.as_context(sel),
                    sel,
                    "fallback-offline",
                    f"Drop unavailable ({e}); fell back to offline tuning.",
                    sel,
                    "",
                    "offline-selection",
                )
        # offline / private
        sel = await self._select(history)
        source = ANCHOR_PRIVATE if self.anchor_mode == ANCHOR_PRIVATE else ANCHOR_OFFLINE
        return (
            self._protocol.as_context(sel),
            sel,
            source,
            "",
            sel,
            "",
            "offline-selection",
        )

    def _today(self):
        client = self._drop_client or DropClient()
        return client.today()
