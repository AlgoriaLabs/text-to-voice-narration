"""Speech engines: Kokoro-82M on the CPU, and a silent fake for tests.

Kokoro-82M (Apache 2.0) runs here through ONNX Runtime, so a narration costs nothing but the machine's time. One
inference barely gets faster with more threads, so each runs on one thread and the chunks of a text run side by
side, one per core: on 4 cores that reads about 2.4 times faster than one inference with 4 threads.

espeak-ng, which turns text into phonemes, keeps global state, so phonemizing is done under a lock. It is quick next
to the inference, which runs without it.
"""

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

import numpy as np

from .text import Chunk

SAMPLE_RATE = 24_000


class Engine(Protocol):
    name: str
    sample_rate: int

    def voices(self) -> frozenset[str]: ...

    def synthesize(self, chunks: list[Chunk], voice: str, language: str, speed: float) -> np.ndarray:
        """Mono float32 samples in -1..1 for the chunks, with each chunk's pause after it."""
        ...


def join(parts: list[np.ndarray], chunks: list[Chunk], sample_rate: int) -> np.ndarray:
    """The chunks' audio in order, with the silence each chunk asks for after it."""
    pieces: list[np.ndarray] = []
    for audio, chunk in zip(parts, chunks):
        pieces.append(np.asarray(audio, dtype=np.float32).ravel())
        if chunk.pause > 0:
            pieces.append(np.zeros(int(chunk.pause * sample_rate), dtype=np.float32))
    return np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.float32)


class KokoroEngine:
    name = "kokoro-82m"
    sample_rate = SAMPLE_RATE

    def __init__(self, model_path: str, voices_path: str, workers: int | None = None):
        import onnxruntime as rt
        from kokoro_onnx import Kokoro

        for path in (model_path, voices_path):
            if not os.path.isfile(path):
                raise FileNotFoundError(f"{path} is missing: run scripts/download-models.sh")
        options = rt.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.graph_optimization_level = rt.GraphOptimizationLevel.ORT_ENABLE_ALL
        session = rt.InferenceSession(model_path, options, providers=["CPUExecutionProvider"])
        self._kokoro = Kokoro.from_session(session, voices_path)
        self._voices = frozenset(self._kokoro.get_voices())
        self.workers = workers or os.cpu_count() or 1
        self._pool = ThreadPoolExecutor(self.workers, thread_name_prefix="kokoro")
        self._phonemes = threading.Lock()

    def voices(self) -> frozenset[str]:
        return self._voices

    def warm_up(self) -> None:
        self.synthesize([Chunk("Ready.", 0.0)], "af_heart", "en-us", 1.0)

    def synthesize(self, chunks: list[Chunk], voice: str, language: str, speed: float) -> np.ndarray:
        if voice not in self._voices:
            raise ValueError(f"unknown voice {voice!r}")
        futures = [self._pool.submit(self._read, chunk.text, voice, language, speed) for chunk in chunks]
        return join([future.result() for future in futures], chunks, self.sample_rate)

    def _read(self, text: str, voice: str, language: str, speed: float) -> np.ndarray:
        with self._phonemes:
            phonemes = self._kokoro.tokenizer.phonemize(text, language)
        if not phonemes.strip():
            return np.zeros(0, dtype=np.float32)
        samples, _ = self._kokoro.create(phonemes, voice=voice, speed=speed, lang=language, is_phonemes=True)
        return samples

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


class FakeEngine:
    """A quiet tone, 60 ms per character: for tests and for trying the payment flow without the model."""

    name = "fake"
    sample_rate = SAMPLE_RATE

    def __init__(self, delay_seconds: float = 0.0):
        self.delay_seconds = delay_seconds
        self.calls = 0

    def voices(self) -> frozenset[str]:
        from .voices import VOICES

        return frozenset(VOICES)

    def synthesize(self, chunks: list[Chunk], voice: str, language: str, speed: float) -> np.ndarray:
        self.calls += 1
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        parts = []
        for chunk in chunks:
            n = int(len(chunk.text) * 0.06 / speed * self.sample_rate)
            t = np.arange(n, dtype=np.float32) / self.sample_rate
            parts.append(0.1 * np.sin(2 * np.pi * 220 * t).astype(np.float32))
        return join(parts, chunks, self.sample_rate)
