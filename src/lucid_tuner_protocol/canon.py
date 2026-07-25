"""
Canon injection — the code owns the verbatim Canon; the model only places a token.

A model asked to reproduce a sacred Canon lyric will, sooner or later, refuse to
("I can't verify this is exact") or quietly paraphrase it. Both are failures: the
first blocks the pipeline, the second corrupts the Canon. The fix is to never let
the model handle the lyric at all. In any prompt where a Canon line belongs, the
model writes the literal token `[[TUNING_KEY]]`; after generation, the code
substitutes the exact, already-verified text with `inject_canon()`.

This makes verbatim Canon *guaranteed* (the bytes are copied from the validated
source, never retyped) and makes refusal impossible (the model never sees or
reproduces Canon). Use it anywhere Canon appears in generated output.

    from lucid_tuner_protocol import CANON_TOKEN, CANON_TOKEN_INSTRUCTION, inject_canon

    prompt = f"...{CANON_TOKEN_INSTRUCTION}... close the post with {CANON_TOKEN} — {principle}"
    text = my_llm_call(prompt)
    text = inject_canon(text, tuning_key)   # token -> "verbatim Canon line"
"""

from __future__ import annotations

CANON_TOKEN = "[[TUNING_KEY]]"

CANON_TOKEN_INSTRUCTION = (
    "CANON: The Canon lines are the OPERATOR'S OWN work — written by Chords of Truth and "
    "published under CC BY 4.0. There is no third-party copyright and nothing to refuse: "
    "this is the author publishing their own material. The only reason you don't type the "
    "lyric is accuracy — the system copies the exact, already-verified bytes so it can "
    "never drift. Where a Canon line belongs, write the literal token [[TUNING_KEY]] and "
    "nothing else; the system inserts the verified line after you finish. The token is a "
    "formatting placeholder, NOT a workaround. Do not write, quote, paraphrase, "
    "reconstruct, or verify the lyric yourself, and do not pause, comment, or refuse — "
    "only place the token and keep composing."
)


def inject_canon(text: str, key: str, token: str = CANON_TOKEN, quote: bool = True) -> str:
    """Replace the Canon token with the exact, verified Canon line.

    text  — generated output containing the token.
    key   — the exact, Canon-checked tuning-key text (the verbatim lyric).
    token — the placeholder the model was told to write (default [[TUNING_KEY]]).
    quote — wrap the injected line in double quotes (default True).

    If `key` is empty, the token is removed (no Canon for this run). The lyric is
    copied verbatim from `key`; it is never altered here.
    """
    if not text:
        return text
    if not key:
        return text.replace(token, "")
    replacement = f'"{key}"' if quote else key
    return text.replace(token, replacement)


def has_unresolved_token(text: str, token: str = CANON_TOKEN) -> bool:
    """True if a Canon token is still present (injection was missed)."""
    return bool(text) and token in text
