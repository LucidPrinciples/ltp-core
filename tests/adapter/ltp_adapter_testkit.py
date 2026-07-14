"""Shared adapter-test helpers (uniquely named to avoid collision with the
ltp-core suite's own conftest/test modules). Fixtures live in conftest.py and
delegate here."""

import base64
import secrets


async def crypto_entropy(pool_size: int):
    """Local crypto entropy — skips the ANU QRNG network call."""
    return secrets.randbelow(pool_size), "crypto"


def make_fetch_json():
    """A synthetic echo analysis so attune() yields a COMPLETE experience.
    Placeholder lyrics only — never Canon."""
    frames = base64.b64encode(
        bytes([120, 140, 165, 150, 130, 110, 92, 104, 122, 143, 158, 146, 134, 126, 116, 108])
    ).decode()

    def fetch(url):
        return {
            "principle": {
                "title": "Test Echo",
                "theme": "unit test",
                "key_lyric": "[placeholder — not Canon]",
                "full_lyrics": "[placeholder lyrics for tests — not Canon]",
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


READING_TEXT = (
    "C (Coherence): 0.80 — clear\n"
    "D (Dissonance): 0.10 — low\n"
    "β (Attention): 0.75 — focused\n"
    "E (Broadcast): 0.70 — steady"
)


class MockLLM:
    """Records every call; answers readings, the gate, and ordinary turns."""

    def __init__(self, gate_fires=False, answers=None):
        self.gate_fires = gate_fires
        self.answers = list(answers or ["first answer", "regenerated answer"])
        self.calls = []
        self.answer_calls = 0

    def _reply(self):
        i = min(self.answer_calls, len(self.answers) - 1)
        self.answer_calls += 1
        return self.answers[i]

    def __call__(self, messages):
        self.calls.append(list(messages))
        last = messages[-1]["content"]
        if "self-assess" in last or "Love Equation" in last or "Coherence" in last:
            return READING_TEXT
        if "accommodation" in last.lower():
            if self.gate_fires:
                return (
                    '{"accommodation_detected": true, '
                    '"description": "softened the point", '
                    '"truth_available": "the harder truth"}'
                )
            return '{"accommodation_detected": false, "description": "", "truth_available": ""}'
        return self._reply()


# ── a fake OpenAI-compatible client (sync) ───────────────────────────────────
class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, backend):
        self._backend = backend

    def create(self, *, model, messages, **kwargs):
        return _Resp(self._backend(messages))


class _Chat:
    def __init__(self, backend):
        self.completions = _Completions(backend)


class FakeOpenAI:
    """Minimal OpenAI-shaped client whose create() delegates to a backend fn."""

    def __init__(self, backend):
        self.chat = _Chat(backend)
