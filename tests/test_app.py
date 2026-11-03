"""The narration API with a fake engine: limits, formats, idempotency, audio files and expiry."""

import io
import json
import time

import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from app import create_app
from narration.engine import FakeEngine
from narration.settings import Settings, audio_base_url, load_tiers, ROOT


@pytest.fixture()
def engine():
    return FakeEngine()


@pytest.fixture()
def client(tmp_path, engine):
    settings = Settings(
        data_dir=tmp_path,
        audio_base_url="https://narration.example.com/audio",
        tiers=load_tiers(ROOT / "provider.config.json"),
    )
    with TestClient(create_app(settings, engine)) as client:
        yield client


def test_narrates_and_serves_the_file(client):
    response = client.post("/tts/narrate-short", json={"text": "Hello there, world.", "voice": "bf_emma"})
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["audioUrl"].startswith("https://narration.example.com/audio/") and out["audioUrl"].endswith(".mp3")
    assert out["format"] == "mp3" and out["mimeType"] == "audio/mpeg"
    assert out["voice"] == "bf_emma" and out["language"] == "English (UK)"
    assert out["characters"] == len("Hello there, world.")
    assert out["sampleRate"] == 24000 and out["durationSeconds"] > 0.5
    assert out["expiresAt"].endswith("Z")

    name = out["audioUrl"].rsplit("/", 1)[1]
    audio = client.get(f"/audio/{name}")
    assert audio.status_code == 200
    assert audio.headers["content-type"] == "audio/mpeg"
    assert len(audio.content) == out["bytes"]
    decoded, rate = sf.read(io.BytesIO(audio.content))
    assert rate == 24000 and abs(len(decoded) / rate - out["durationSeconds"]) < 0.2


@pytest.mark.parametrize(("fmt", "mime", "ext"), [("opus", "audio/ogg", ".ogg"), ("wav", "audio/wav", ".wav")])
def test_other_formats(client, fmt, mime, ext):
    out = client.post("/tts/narrate-short", json={"text": "Bonjour à tous.", "voice": "ff_siwis", "format": fmt}).json()
    assert out["mimeType"] == mime and out["audioUrl"].endswith(ext) and out["language"] == "French"
    assert client.get("/audio/" + out["audioUrl"].rsplit("/", 1)[1]).headers["content-type"] == mime


def test_each_tier_holds_its_own_limit(client):
    assert client.post("/tts/narrate-short", json={"text": "a" * 501}).status_code == 413
    assert client.post("/tts/narrate-medium", json={"text": "a " * 1000}).status_code == 200
    assert client.post("/tts/narrate-medium", json={"text": "a" * 2001}).status_code == 413
    assert client.post("/tts/narrate-huge", json={"text": "hi"}).status_code == 404


def test_rejects_bad_input(client):
    assert client.post("/tts/narrate-short", json={"text": "hi", "voice": "jf_alpha"}).status_code == 422
    assert client.post("/tts/narrate-short", json={"text": "hi", "speed": 3}).status_code == 422
    assert client.post("/tts/narrate-short", json={"text": "hi", "extra": 1}).status_code == 422
    assert client.post("/tts/narrate-short", json={"text": "?!..."}).status_code == 422


def test_the_same_job_is_answered_once(client, engine):
    body = {"text": "Only once, please.", "voice": "am_adam"}
    first = client.post("/tts/narrate-short", json=body, headers={"Idempotency-Key": "job-1"}).json()
    again = client.post("/tts/narrate-short", json=body, headers={"Idempotency-Key": "job-1"}).json()
    other = client.post("/tts/narrate-short", json=body, headers={"Idempotency-Key": "job-2"}).json()
    assert first == again
    assert other["audioUrl"] != first["audioUrl"]
    assert engine.calls == 2


def test_audio_names_are_checked(client):
    assert client.get("/audio/..%2Fnarrations%2Fx.json").status_code == 404
    assert client.get("/audio/short.mp3").status_code == 404
    assert client.get("/audio/" + "A" * 24 + ".mp3").status_code == 404


def test_expired_files_are_removed(client, tmp_path):
    out = client.post("/tts/narrate-short", json={"text": "Gone tomorrow."}, headers={"Idempotency-Key": "job-x"}).json()
    store = client.app.state.store
    assert store.cleanup() == 0
    assert store.cleanup(now=time.time() + store.retention_seconds + 1) == 2
    assert client.get("/audio/" + out["audioUrl"].rsplit("/", 1)[1]).status_code == 404


def test_health(client):
    body = client.get("/healthz").json()
    assert body["ok"] and body["engine"] == "fake" and body["tiers"] == ["narrate-long", "narrate-medium", "narrate-short"]


def test_audio_base_url_follows_the_public_origin():
    assert audio_base_url({"PUBLIC_ORIGIN": "https://a.example.com/"}) == "https://a.example.com/audio"
    assert audio_base_url({"PUBLIC_ORIGIN": "http://localhost:8787"}) == "http://localhost:8000/audio"
    assert audio_base_url({"AUDIO_BASE_URL": "https://cdn.example.com/a/", "PUBLIC_ORIGIN": "https://x.example.com"}) == "https://cdn.example.com/a"


def test_fake_engine_refuses_a_public_origin(tmp_path, monkeypatch):
    from app import make_engine

    monkeypatch.delenv("ALLOW_FAKE_ENGINE", raising=False)
    with pytest.raises(RuntimeError):
        make_engine(Settings(engine="fake", audio_base_url="https://narration.example.com/audio"))
    assert isinstance(make_engine(Settings(engine="fake")), FakeEngine)
