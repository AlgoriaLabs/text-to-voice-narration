"""Settings, from the environment (and .env through npm run dev), and the tiers from provider.config.json.

provider.config.json is the one place a tier's price and character limit are written. The gateway reads it to
publish the manifest and check input before payment; this app reads the same file, so each /tts/<service>
endpoint holds the same limit.
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Tier:
    name: str
    max_chars: int
    price: str


@dataclass(frozen=True)
class Settings:
    engine: str = "kokoro"
    models_dir: Path = ROOT / "models"
    kokoro_model: str = "kokoro-v1.0.onnx"
    kokoro_voices: str = "voices-v1.0.bin"
    workers: int | None = None
    data_dir: Path = ROOT / "data"
    audio_base_url: str = "http://localhost:8000/audio"
    retention_seconds: int = 90_000
    config_path: Path = ROOT / "provider.config.json"
    tiers: dict[str, Tier] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        config_path = Path(env.get("PROVIDER_CONFIG", ROOT / "provider.config.json"))
        workers = env.get("TTS_WORKERS", "").strip()
        return cls(
            engine=env.get("TTS_ENGINE", "kokoro").strip() or "kokoro",
            models_dir=Path(env.get("MODELS_DIR", ROOT / "models")),
            kokoro_model=env.get("KOKORO_MODEL", "kokoro-v1.0.onnx"),
            kokoro_voices=env.get("KOKORO_VOICES", "voices-v1.0.bin"),
            workers=int(workers) if workers else None,
            data_dir=Path(env.get("DATA_DIR", ROOT / "data")),
            audio_base_url=audio_base_url(env),
            retention_seconds=int(env.get("AUDIO_RETENTION_SECONDS", "90000")),
            config_path=config_path,
            tiers=load_tiers(config_path),
        )


def audio_base_url(env: dict[str, str]) -> str:
    """Where clients fetch audio: AUDIO_BASE_URL, else <PUBLIC_ORIGIN>/audio for an https origin, else this app."""
    explicit = env.get("AUDIO_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    origin = env.get("PUBLIC_ORIGIN", "").strip().rstrip("/")
    if urlparse(origin).scheme == "https":
        return f"{origin}/audio"
    return "http://localhost:8000/audio"


def load_tiers(config_path: Path) -> dict[str, Tier]:
    """Each service whose upstream is /tts/<its name>, with the text limit of its inputSchema."""
    config = json.loads(Path(config_path).read_text("utf-8"))
    tiers: dict[str, Tier] = {}
    for service in config["services"]:
        path = urlparse(service["upstream"]["url"]).path
        if not path.startswith("/tts/"):
            continue
        name = path.removeprefix("/tts/")
        if name != service["name"]:
            raise ValueError(f"service {service['name']!r} must call /tts/{service['name']}, not {path}")
        max_chars = service["inputSchema"]["properties"]["text"]["maxLength"]
        tiers[name] = Tier(name=name, max_chars=int(max_chars), price=service["price"])
    if not tiers:
        raise ValueError(f"{config_path} has no /tts/<service> services")
    return tiers
