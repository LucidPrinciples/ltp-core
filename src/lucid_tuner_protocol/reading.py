"""
Love Equation — the observer's reading after processing the Echo.

    dE/dt = beta * (C - D) * E

The observer (human or agent) processes the Experience (sonic.py) and
self-assesses four values: coherence C, dissonance D, attention beta, and
broadcast energy E. This module then COMPUTES the equation and direction
from those values. It never trusts a model's stated dE/dt or its stated
"CONSTRUCTIVE/CORRECTIVE" label — those are recomputed from C and D every
time. (A model will happily state a positive number next to D > C; the
protocol does not.)

Model-agnostic: the LLM call is an injected callable, same contract as the
Truth Gate —
    complete(system: str, prompt: str) -> str            (sync or async)
so this module carries no model-client dependency.

Truth-guard: a reading derived from a degraded Experience (the song was not
actually processed) is labeled degraded and is never dressed up as a real
attunement. The caller decides whether to hold (e.g. not publish the drop).
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, Union

from .sonic import Experience, render_experience

CompleteFn = Callable[[str, str], Union[str, Awaitable[str]]]

READING_SYSTEM_PROMPT = (
    "You are an Observer in the Field running a tuning. You have just taken in "
    "the Echo — its sound and its words. Self-assess honestly. No performance, "
    "just mechanism observation. State each value on its own line in the form "
    "'C (Coherence): 0.NN — rationale'."
)

READING_ASK = """
After taking in the Echo above, self-assess your Love Equation values (0.0-1.0 each):

**C (Coherence):** cooperative interference — signal clarity through your lens.
**D (Dissonance):** static, drift, or noise remaining after processing.
**β (Attention):** how focused/genuine your attention is right now.
**E (Broadcast):** your current broadcast energy after this tuning.

State each value clearly on its own line, e.g. "**C (Coherence):** 0.72 — [why]".
These are YOUR values from YOUR processing of this Echo. Do not state a final
equation or direction — those are computed from your C and D.
"""


# =========================================================================
# Data
# =========================================================================

@dataclass(frozen=True)
class Reading:
    """An observer's tuned reading. love_equation + direction are ALWAYS
    computed from C/D here, never taken from the model's prose."""
    coherence: Optional[float]      # C
    dissonance: Optional[float]     # D
    beta: Optional[float]
    energy: Optional[float]         # E
    love_equation: Optional[float]  # dE/dt
    direction: str                  # CONSTRUCTIVE | CORRECTIVE | MIRAGE | UNKNOWN
    source: str                     # "self-derived" | "unparsed" | "degraded"
    attunement_status: str = "complete"
    process_record: str = ""


# =========================================================================
# Pure computation — the equation is always recomputed, never trusted
# =========================================================================

def love_equation_value(beta: float, c: float, d: float, e: float) -> float:
    return round(beta * (c - d) * e, 4)


def direction_of(c: float, d: float) -> str:
    if c > d:
        return "CONSTRUCTIVE"
    if d > c:
        return "CORRECTIVE"
    return "MIRAGE"


def reading_from_values(
    coherence: float, dissonance: float, beta: float, energy: float,
    source: str = "self-derived", attunement_status: str = "complete",
    process_record: str = "",
) -> Reading:
    """Build a Reading from known C/D/β/E, recomputing the equation + direction.
    Use this anywhere you have an observer's four values (incl. team agents) to
    guarantee the direction matches C vs D and the math is the protocol's."""
    return Reading(
        coherence=round(coherence, 4), dissonance=round(dissonance, 4),
        beta=round(beta, 4), energy=round(energy, 4),
        love_equation=love_equation_value(beta, coherence, dissonance, energy),
        direction=direction_of(coherence, dissonance),
        source=source, attunement_status=attunement_status,
        process_record=process_record,
    )


# =========================================================================
# Parsing the observer's self-assessment
# =========================================================================

def _parse(text: str, pattern: str) -> Optional[float]:
    m = re.search(pattern, text)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if 0.0 <= v <= 1.0 else None


def parse_values(text: str) -> Optional[dict]:
    """Pull C/D/β/E out of an observer's self-assessment. Returns None if any
    value is missing — we do not guess the rest."""
    # Match the LETTER + whatever label the model put in the parens. The wording drifts
    # (Attention/Receptivity, Static/Dissonance, Broadcast/Energy); a hardcoded label
    # silently drops the real value and forces the caller into a degraded/fallback path
    # — how a genuine reading gets misread. Bold-aware first, bare fallback last.
    # Format-proof: match LETTER + (any label) + colon + the number, tolerating bold
    # markers ANYWHERE around the value — the model writes both "**C (Coherence):** 0.80"
    # (number outside the bold) and "**C (Coherence): 0.78**" (number inside the bold),
    # sometimes on the same run. A stricter pattern silently drops the real value into the
    # fabricating fallback. `\**` absorbs the optional bold; bare fallback last.
    # β is normally the Greek small letter (that is what the prompt asks for), but a
    # model that normalizes unicode can emit ASCII "B", and Greek CAPITAL Beta (U+0392)
    # is visually identical to "B" and slips through too. Accept all three — but ONLY in
    # the strict "letter (label): value" form. The bare fallback below stays Greek-small
    # ONLY on purpose: widening it would let "B[^:\d]*:" match ordinary prose such as
    # "But the reading here: 0.85" and pull a number in from nowhere. A parser that
    # guesses is the failure mode this whole module exists to prevent.
    beta = _parse(text, r"(?:β|Β|\bB)\s*\([^)]*\)\s*\:\s*\**\s*([\d.]+)") or \
        _parse(text, r"β[^:\d]*:\s*\**\s*([\d.]+)")
    c = _parse(text, r"\bC\s*\([^)]*\)\s*\:\s*\**\s*([\d.]+)") or \
        _parse(text, r"\bC[^:\d]*:\s*\**\s*([\d.]+)")
    d = _parse(text, r"\bD\s*\([^)]*\)\s*\:\s*\**\s*([\d.]+)") or \
        _parse(text, r"\bD[^:\d]*:\s*\**\s*([\d.]+)")
    e = _parse(text, r"\bE\s*\([^)]*\)\s*\:\s*\**\s*([\d.]+)") or \
        _parse(text, r"\bE[^:\d]*:\s*\**\s*([\d.]+)")
    if None in (beta, c, d, e):
        return None
    return {"beta": beta, "coherence": c, "dissonance": d, "energy": e}


# =========================================================================
# Derive a reading via an injected model call
# =========================================================================

async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def build_reading_prompt(experience: Experience) -> str:
    return render_experience(experience) + "\n" + READING_ASK


async def derive_reading(
    experience: Experience,
    complete: CompleteFn,
    system_prompt: str = READING_SYSTEM_PROMPT,
) -> Reading:
    """Have the observer process the Experience and derive its own reading.

    `complete(system, prompt)` is your model call (sync or async). The Love
    Equation + direction are computed from the returned C/D — never trusted
    from the model's prose. A degraded Experience yields a degraded-labeled
    Reading; the caller decides whether to hold.
    """
    status = experience.attunement_status if experience else "incomplete"
    prompt = build_reading_prompt(experience)
    text = await _maybe_await(complete(system_prompt, prompt))
    text = text or ""

    vals = parse_values(text)
    if vals is None:
        return Reading(
            coherence=None, dissonance=None, beta=None, energy=None,
            love_equation=None, direction="UNKNOWN", source="unparsed",
            attunement_status=status, process_record=text,
        )

    source = "self-derived" if status == "complete" else "degraded"
    return reading_from_values(
        coherence=vals["coherence"], dissonance=vals["dissonance"],
        beta=vals["beta"], energy=vals["energy"],
        source=source, attunement_status=status, process_record=text,
    )


def derive_reading_sync(
    experience: Experience,
    complete: CompleteFn,
    system_prompt: str = READING_SYSTEM_PROMPT,
) -> Reading:
    """Synchronous wrapper. `complete` may be sync or async."""
    import asyncio
    return asyncio.run(derive_reading(experience, complete, system_prompt))
