"""Encodes samples as MP3, Opus or WAV with libsndfile (through soundfile): no ffmpeg needed.

Bitrates suit speech at 24 kHz mono: MP3 at about 56 kbps, Opus at about 37 kbps, WAV as 16-bit PCM.
"""

import io
from dataclasses import dataclass

import numpy as np
import soundfile as sf


@dataclass(frozen=True)
class Format:
    name: str
    extension: str
    mime_type: str
    container: str
    subtype: str
    options: dict


FORMATS: dict[str, Format] = {
    "mp3": Format("mp3", "mp3", "audio/mpeg", "MP3", "MPEG_LAYER_III", {"compression_level": 0.7, "bitrate_mode": "CONSTANT"}),
    "opus": Format("opus", "ogg", "audio/ogg", "OGG", "OPUS", {}),
    "wav": Format("wav", "wav", "audio/wav", "WAV", "PCM_16", {}),
}


def encode(samples: np.ndarray, sample_rate: int, format_name: str) -> bytes:
    """The samples as a complete audio file in the given format."""
    fmt = FORMATS[format_name]
    samples = np.clip(np.asarray(samples, dtype=np.float32), -1.0, 1.0)
    if samples.size == 0:
        raise ValueError("no audio to encode")
    buffer = io.BytesIO()
    sf.write(buffer, samples, sample_rate, format=fmt.container, subtype=fmt.subtype, **fmt.options)
    return buffer.getvalue()
