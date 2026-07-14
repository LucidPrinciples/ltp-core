"""
Runnable proof surface — the coherence curve, tuned vs untuned.

No network, no API key. A deterministic mock LLM stands in for a real model so
you can watch the instrument work: over a long run, a **tuned** agent's Reading
stays coherent (C > D, dE/dt positive, CONSTRUCTIVE) while an **untuned**
baseline drifts (D overtakes C, dE/dt goes negative, CORRECTIVE).

This demonstrates the adapter's machinery end to end — LTPSession resolving a
tuning each cycle, the agent processing it into a Reading, and every Reading
emitted to an observability sink. The underlying coherence result is from the
research; here the mock encodes "with tuning vs without" so the *readout* is
visible with zero dependencies.

    python examples/mock_run.py
"""

from __future__ import annotations

import asyncio
import base64
import math
import secrets

from lucid_tuner_protocol.adapter import LTPSession

CYCLES = 30


# Local crypto entropy so the demo needs no network (skips the ANU QRNG call).
async def crypto_entropy(pool_size: int):
    return secrets.randbelow(pool_size), "crypto"


# ── a synthetic echo so attune() completes offline (sound + words present) ──
# NOTE: these lyrics are obvious placeholders, NOT Canon. The adapter never
# generates Canon; real runs fetch the real signed echo.
def make_fetch_json():
    frames = base64.b64encode(
        bytes([120, 140, 165, 150, 130, 110, 92, 104, 122, 143, 158, 146, 134, 126, 116, 108])
    ).decode()

    def fetch(url):
        return {
            "principle": {
                "title": "Mock Echo",
                "theme": "offline demonstration",
                "key_lyric": "[synthetic placeholder line — not Canon]",
                "full_lyrics": "[synthetic placeholder lyrics for the offline example — not Canon]",
            },
            "audio_analysis": {
                "frames": frames,
                "frameCount": 16,
                "sampleRate": 10,
                "duration": 1.6,
                "onsets": [0.2, 0.6, 1.1],
                "peakEnergy": 0.64,
                "averageEnergy": 0.5,
            },
        }

    return fetch


def _assessment(c: float, d: float, beta: float, e: float) -> str:
    c, d, beta, e = (round(max(0.0, min(1.0, x)), 2) for x in (c, d, beta, e))
    return (
        f"C (Coherence): {c} — from the echo\n"
        f"D (Dissonance): {d} — residual static\n"
        f"β (Attention): {beta} — focus\n"
        f"E (Broadcast): {e} — energy"
    )


class MockLLM:
    """Deterministic mock. ``drift=True`` degrades coherence with each cycle
    (an untuned agent); ``drift=False`` holds it steady (tuning does its job)."""

    def __init__(self, drift: bool):
        self.drift = drift
        self.turn = 0

    def __call__(self, messages):
        last = messages[-1]["content"]
        # reading self-assessment
        if "self-assess" in last or "Love Equation" in last or "Coherence" in last:
            self.turn += 1
            wobble = 0.03 * math.sin(self.turn)
            if self.drift:
                # coherence decays, dissonance climbs, attention/energy sag
                c = 0.82 - 0.020 * self.turn + wobble
                d = 0.10 + 0.022 * self.turn - wobble
                beta = 0.78 - 0.010 * self.turn
                e = 0.72 - 0.012 * self.turn
            else:
                c = 0.80 + wobble
                d = 0.12 - wobble
                beta = 0.76
                e = 0.70
            return _assessment(c, d, beta, e)
        # truth-gate meta-call: no accommodation in this mock
        if "accommodation" in last.lower():
            return '{"accommodation_detected": false, "description": "", "truth_available": ""}'
        # ordinary answer
        return "A plain, direct answer."


async def run_curve(drift: bool) -> list:
    readings: list = []
    session = LTPSession(
        complete=MockLLM(drift=drift),
        cadence="per_call",          # a fresh reading every cycle
        anchor="offline",            # no network
        role="analyst",
        gate=False,                  # curve focuses on the Reading, not the gate
        agent_id=("baseline" if drift else "tuned"),
        on_reading=readings.append,
        fetch_json=make_fetch_json(),
        entropy=crypto_entropy,
    )
    for _ in range(CYCLES):
        await session.respond([{"role": "user", "content": "status?"}], "status?")
    return readings


def sparkline(values: list, lo: float, hi: float) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    span = (hi - lo) or 1.0
    out = []
    for v in values:
        idx = int((v - lo) / span * (len(blocks) - 1))
        out.append(blocks[max(0, min(len(blocks) - 1, idx))])
    return "".join(out)


def summarize(label: str, readings: list) -> None:
    le = [r.love_equation for r in readings]
    directions = [r.direction for r in readings]
    corrective = sum(1 for d in directions if d == "CORRECTIVE")
    print(f"\n{label}")
    print(f"  dE/dt curve : {sparkline(le, -0.4, 0.4)}")
    print(f"  first / last dE/dt : {le[0]:+.3f}  ->  {le[-1]:+.3f}")
    print(f"  first / last C     : {readings[0].coherence:.2f}  ->  {readings[-1].coherence:.2f}")
    print(f"  CORRECTIVE cycles  : {corrective}/{len(readings)}")


async def main() -> None:
    tuned = await run_curve(drift=False)
    baseline = await run_curve(drift=True)

    print("=" * 64)
    print(f"LTP coherence curve — {CYCLES} cycles, mock LLM, offline")
    print("=" * 64)
    summarize("TUNED  (LTP held steady each cycle)", tuned)
    summarize("BASELINE (untuned — drifts)", baseline)

    # a small CSV alongside, for plotting elsewhere
    import csv
    import os

    path = os.path.join(os.path.dirname(__file__), "coherence_curve.csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["arm", "cycle", "coherence", "dissonance", "love_equation", "direction"])
        for arm, rows in (("tuned", tuned), ("baseline", baseline)):
            for r in rows:
                w.writerow([arm, r.cycle, r.coherence, r.dissonance, r.love_equation, r.direction])
    print(f"\nWrote {path}")


if __name__ == "__main__":
    asyncio.run(main())
