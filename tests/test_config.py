"""provider.config.json and app.py tell the same story: what agents read before they pay is what the API does."""

import json
from decimal import Decimal

from app import NarrateOut
from narration.audio import FORMATS
from narration.settings import ROOT, load_tiers
from narration.text import speakable
from narration.voices import DEFAULT_VOICE, LANGUAGES, VOICES

CONFIG = json.loads((ROOT / "provider.config.json").read_text("utf-8"))
SERVICES = CONFIG["services"]


def test_is_a_mainnet_config_that_reads_its_settings_from_the_environment():
    assert CONFIG["network"] == "stellar:pubnet"
    assert CONFIG["facilitator"] == "https://channels.openzeppelin.com/x402"
    assert CONFIG["facilitatorHeaders"] == {"Authorization": "env:FACILITATOR_AUTH"}
    assert CONFIG["payTo"] == "env:PAY_TO" and CONFIG["baseUrl"] == "env:PUBLIC_ORIGIN"
    assert "dev" not in CONFIG


def test_search_finds_it_by_the_words_buyers_type():
    # On mainnet, search reads only the provider's name and description.
    words = (CONFIG["provider"]["name"] + " " + CONFIG["provider"]["description"]).lower()
    for word in ("text-to-speech", "tts", "voice", "narration", "audio", "speech", "audiobook", "podcast", "voiceover"):
        assert word in words
    assert len(CONFIG["provider"]["description"]) <= 500


def test_tiers_grow_in_length_and_price():
    tiers = list(load_tiers(ROOT / "provider.config.json").values())
    assert [t.name for t in tiers] == ["narrate-short", "narrate-medium", "narrate-long"]
    assert [t.max_chars for t in tiers] == sorted(t.max_chars for t in tiers)
    prices = [Decimal(t.price) for t in tiers]
    assert prices == sorted(prices)
    for tier in tiers:
        # About one cent per 1,000 characters of the tier's limit.
        assert Decimal(tier.price) / tier.max_chars * 1000 <= Decimal("0.01")


def test_schemas_match_the_api():
    for service in SERVICES:
        properties = service["inputSchema"]["properties"]
        assert properties["voice"]["enum"] == list(VOICES) and properties["voice"]["default"] == DEFAULT_VOICE
        assert set(properties["format"]["enum"]) == set(FORMATS)
        assert properties["speed"]["minimum"] == 0.5 and properties["speed"]["maximum"] == 2
        assert service["inputSchema"]["additionalProperties"] is False
        output = service["outputSchema"]
        assert set(output["required"]) == set(NarrateOut.model_fields)
        assert set(output["properties"]["mimeType"]["enum"]) == {f.mime_type for f in FORMATS.values()}
        assert service["upstream"]["url"] == f"http://127.0.0.1:8000/tts/{service['name']}"


def test_examples_look_like_real_answers():
    for service in SERVICES:
        for example in service["examples"]:
            given, answer = example["input"], example["output"]
            assert speakable(given["text"])
            assert answer["voice"] == given["voice"] and answer["language"] == LANGUAGES[given["voice"][0]][1]
            fmt = FORMATS[given["format"]]
            assert answer["mimeType"] == fmt.mime_type and answer["audioUrl"].endswith("." + fmt.extension)
            assert answer["characters"] == len(given["text"])
            NarrateOut(**answer)


def test_on_success_work_fits_inside_the_payment_window():
    # [S2]: an on-success service's expected work is at most half of maxTimeoutSeconds.
    for service in SERVICES:
        if service["charge"] == "on-success":
            assert service["expectedDurationSeconds"] <= CONFIG["maxTimeoutSeconds"] / 2
