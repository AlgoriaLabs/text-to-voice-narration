"""Kokoro itself, when its model files are in models/ (scripts/download-models.sh). Skipped otherwise."""

import time

import numpy as np
import pytest

from narration.settings import Settings
from narration.text import chunk, normalize

settings = Settings.from_env({})
MODEL = settings.models_dir / settings.kokoro_model
VOICES_FILE = settings.models_dir / settings.kokoro_voices
pytestmark = pytest.mark.skipif(not (MODEL.exists() and VOICES_FILE.exists()), reason="Kokoro model files not downloaded")


@pytest.fixture(scope="module")
def engine():
    from narration.engine import KokoroEngine

    engine = KokoroEngine(str(MODEL), str(VOICES_FILE))
    yield engine
    engine.close()


def test_offers_every_voice_in_the_schema(engine):
    from narration.voices import VOICES

    assert set(VOICES) <= engine.voices()


@pytest.mark.parametrize(("voice", "language", "text"), [
    ("af_heart", "en-us", "The lighthouse stood at the edge of the cliff."),
    ("ef_dora", "es", "El faro estaba al borde del acantilado."),
    ("hf_alpha", "hi", "प्रकाशस्तंभ चट्टान के किनारे खड़ा था।"),
])
def test_speaks(engine, voice, language, text):
    audio = engine.synthesize(chunk(normalize(text), engine.workers), voice, language, 1.0)
    seconds = len(audio) / engine.sample_rate
    assert 1.0 < seconds < 8.0
    assert np.abs(audio).max() > 0.05


def test_parallel_chunks_join_in_order(engine):
    text = normalize("One. Two. Three. Four. Five. Six. Seven. Eight. " * 6)
    chunks = chunk(text, workers=4)
    started = time.monotonic()
    together = engine.synthesize(chunks, "am_michael", "en-us", 1.0)
    assert time.monotonic() - started < 120
    first = engine.synthesize(chunks[:1], "am_michael", "en-us", 1.0)
    # Same model, same input: the first chunk's audio opens the joined audio.
    assert np.allclose(together[: len(first) - 2400], first[: len(first) - 2400], atol=1e-4)
