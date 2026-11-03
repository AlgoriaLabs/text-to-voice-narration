"""The voices this service offers, and the language each one speaks.

Kokoro-82M voice ids start with two letters: the language and the gender, such as "af_heart" (American English,
female). Japanese and Mandarin voices are left out: Kokoro needs a separate phonemizer for them to sound right.
provider.config.json lists the same ids in each service's inputSchema; tests/test_config.py keeps the two in step.
"""

DEFAULT_VOICE = "af_heart"

# First letter of a voice id -> (language code for the phonemizer, language name).
LANGUAGES: dict[str, tuple[str, str]] = {
    "a": ("en-us", "English (US)"),
    "b": ("en-gb", "English (UK)"),
    "e": ("es", "Spanish"),
    "f": ("fr-fr", "French"),
    "h": ("hi", "Hindi"),
    "i": ("it", "Italian"),
    "p": ("pt-br", "Portuguese (Brazil)"),
}

VOICES: tuple[str, ...] = (
    # American English
    "af_heart", "af_alloy", "af_aoede", "af_bella", "af_jessica", "af_kore", "af_nicole", "af_nova", "af_river",
    "af_sarah", "af_sky", "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam", "am_michael", "am_onyx", "am_puck",
    "am_santa",
    # British English
    "bf_alice", "bf_emma", "bf_isabella", "bf_lily", "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    # Spanish
    "ef_dora", "em_alex", "em_santa",
    # French
    "ff_siwis",
    # Hindi
    "hf_alpha", "hf_beta", "hm_omega", "hm_psi",
    # Italian
    "if_sara", "im_nicola",
    # Portuguese (Brazil)
    "pf_dora", "pm_alex", "pm_santa",
)


def language_of(voice: str) -> str:
    """The phonemizer language for a voice id, such as "en-us" for "af_heart"."""
    try:
        return LANGUAGES[voice[0]][0]
    except (IndexError, KeyError):
        raise ValueError(f"unknown voice {voice!r}") from None
