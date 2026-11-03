"""Text to Speech Narration: the service itself, a FastAPI app that knows nothing about payments.

The Provider Kit gateway (provider.config.json) stands in front of it. It publishes the manifest, takes the USDC
payment, queues jobs and keeps them for recovery, and POSTs only validated input here, to /tts/<service>. Each
service is a length tier: the longer the text, the higher the price. Keep the models below in step with the schemas
in provider.config.json (tests/test_config.py checks): agents read those before they pay.

Endpoints, on 127.0.0.1:8000 (inside the container only):
  POST /tts/{service}   the narration: text in, a link to the audio file out
  GET  /audio/{file}    the audio files (in production Caddy serves this folder itself, at <PUBLIC_ORIGIN>/audio/)
  GET  /healthz         whether the model is loaded

`npm run dev` starts it next to the gateway.
"""

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from narration.audio import FORMATS, encode
from narration.engine import Engine, FakeEngine, KokoroEngine
from narration.settings import Settings
from narration.store import NarrationStore
from narration.text import chunk, normalize, speakable
from narration.voices import DEFAULT_VOICE, LANGUAGES, VOICES, language_of

log = logging.getLogger("narration")
CLEANUP_EVERY_SECONDS = 600


class NarrateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, description="The text to read aloud")
    voice: str = Field(default=DEFAULT_VOICE, description="Voice id; its first letter sets the language")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speaking rate, 1 is normal")
    format: Literal["mp3", "opus", "wav"] = Field(default="mp3", description="Audio file format")

    @field_validator("voice")
    @classmethod
    def known_voice(cls, voice: str) -> str:
        if voice not in VOICES:
            raise ValueError("unknown voice")
        return voice


class NarrateOut(BaseModel):
    audioUrl: str
    format: str
    mimeType: str
    durationSeconds: float
    characters: int
    voice: str
    language: str
    sampleRate: int
    bytes: int
    expiresAt: str


def make_engine(settings: Settings) -> Engine:
    if settings.engine == "kokoro":
        engine = KokoroEngine(
            str(settings.models_dir / settings.kokoro_model),
            str(settings.models_dir / settings.kokoro_voices),
            settings.workers,
        )
        engine.warm_up()
        return engine
    if settings.engine == "fake":
        # A tone instead of speech: only for tests and for trying the flow without the model. Never sell it.
        if settings.audio_base_url.startswith("https://") and os.environ.get("ALLOW_FAKE_ENGINE") != "1":
            raise RuntimeError("TTS_ENGINE=fake refuses to run with a public https origin")
        return FakeEngine()
    raise RuntimeError(f"unknown TTS_ENGINE {settings.engine!r}: use kokoro")


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.engine = engine or make_engine(settings)
        app.state.store = NarrationStore(settings.data_dir, settings.retention_seconds)
        stop = threading.Event()

        def clean() -> None:
            while not stop.wait(CLEANUP_EVERY_SECONDS):
                try:
                    removed = app.state.store.cleanup()
                    if removed:
                        log.info("removed %d expired files", removed)
                except Exception:  # noqa: BLE001 - keep cleaning next time
                    log.exception("cleanup failed")

        app.state.store.cleanup()
        cleaner = threading.Thread(target=clean, name="cleanup", daemon=True)
        cleaner.start()
        log.info("ready: engine %s, %d tiers, audio at %s", app.state.engine.name, len(settings.tiers), settings.audio_base_url)
        yield
        stop.set()
        close = getattr(app.state.engine, "close", None)
        if close:
            close()

    app = FastAPI(title="Text to Speech Narration", lifespan=lifespan)
    app.state.settings = settings

    @app.post("/tts/{service}", summary="Narrate", response_model=NarrateOut)
    def narrate(service: str, body: NarrateIn, idempotency_key: str | None = Header(default=None)) -> NarrateOut:
        tier = settings.tiers.get(service)
        if tier is None:
            raise HTTPException(404, "no such service")
        text = normalize(body.text)
        if len(text) > tier.max_chars:
            raise HTTPException(413, f"{service} takes up to {tier.max_chars} characters")
        if not speakable(text):
            raise HTTPException(422, "the text has nothing to read aloud")

        store: NarrationStore = app.state.store
        engine: Engine = app.state.engine
        key = store.key(idempotency_key, service, body.model_dump()) if idempotency_key else None

        def work() -> NarrateOut:
            if key is not None and (found := store.find(key)) is not None:
                log.info("job %s: answered again from its stored result", idempotency_key)
                return NarrateOut(**found)
            started = time.monotonic()
            language = language_of(body.voice)
            workers = getattr(engine, "workers", 1)
            samples = engine.synthesize(chunk(text, workers), body.voice, language, body.speed)
            fmt = FORMATS[body.format]
            data = encode(samples, engine.sample_rate, body.format)
            name, expires = store.save_audio(data, fmt.extension)
            output = NarrateOut(
                audioUrl=f"{settings.audio_base_url}/{name}",
                format=fmt.name,
                mimeType=fmt.mime_type,
                durationSeconds=round(len(samples) / engine.sample_rate, 2),
                characters=len(text),
                voice=body.voice,
                language=LANGUAGES[body.voice[0]][1],
                sampleRate=engine.sample_rate,
                bytes=len(data),
                expiresAt=datetime.fromtimestamp(expires, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            if key is not None:
                store.remember(key, name, output.model_dump())
            log.info(
                "%s: %d chars -> %.1f s of audio in %.1f s",
                service, len(text), output.durationSeconds, time.monotonic() - started,
            )
            return output

        if key is None:
            return work()
        with store.lock(key):
            return work()

    @app.get("/audio/{name}", include_in_schema=False)
    def audio(name: str) -> FileResponse:
        path = app.state.store.audio_path(name)
        if path is None:
            raise HTTPException(404, "not found")
        mime = {f.extension: f.mime_type for f in FORMATS.values()}[path.suffix.lstrip(".")]
        return FileResponse(
            path,
            media_type=mime,
            headers={"Cache-Control": "public, max-age=3600", "Access-Control-Allow-Origin": "*"},
        )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict:
        engine = app.state.engine
        return {"ok": True, "engine": engine.name, "voices": len(engine.voices()), "tiers": sorted(settings.tiers)}

    return app


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app()
