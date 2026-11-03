"""Text clean-up and chunking."""

from narration.text import MAX_CHUNK, PARAGRAPH_PAUSE, SENTENCE_PAUSE, chunk, normalize, speakable


def test_normalize_cleans_whitespace_and_control_characters():
    assert normalize("  Hello\u0007   world.\r\n\r\n\r\n\r\nBye  ") == "Hello world.\n\nBye"


def test_speakable_needs_a_letter_or_digit():
    assert speakable("Hola, ¿qué tal?")
    assert speakable("नमस्ते")
    assert speakable("42")
    assert not speakable("... ?! 😀")


def test_short_text_is_one_chunk_without_a_trailing_pause():
    chunks = chunk("One sentence. Two sentences.", workers=4)
    assert [c.text for c in chunks] == ["One sentence. Two sentences."]
    assert chunks[-1].pause == 0.0


def test_long_text_is_split_at_sentences_for_each_worker():
    sentence = "The ships passed slowly beyond the dark horizon tonight. "
    text = normalize(sentence * 20)
    chunks = chunk(text, workers=4)
    assert len(chunks) >= 4
    assert all(len(c.text) <= MAX_CHUNK for c in chunks)
    assert all(c.text.endswith(".") for c in chunks)
    assert all(c.pause == SENTENCE_PAUSE for c in chunks[:-1])
    assert " ".join(c.text for c in chunks) == text


def test_paragraphs_get_a_longer_pause():
    chunks = chunk(normalize("First paragraph.\n\nSecond paragraph."), workers=1)
    assert [c.text for c in chunks] == ["First paragraph.", "Second paragraph."]
    assert chunks[0].pause == PARAGRAPH_PAUSE


def test_a_very_long_sentence_is_cut_at_commas_then_spaces():
    clause = "and then another clause follows, "
    text = normalize("It began " + clause * 30 + "until the end.")
    chunks = chunk(text, workers=2)
    assert all(len(c.text) <= MAX_CHUNK for c in chunks)
    assert " ".join(c.text for c in chunks) == text
    no_breaks = normalize("word " * 200)
    assert all(len(c.text) <= MAX_CHUNK for c in chunk(no_breaks, workers=1))


def test_unspeakable_chunks_are_dropped():
    chunks = chunk(normalize("Hello there.\n\n...\n\nGoodbye."), workers=1)
    assert [c.text for c in chunks] == ["Hello there.", "Goodbye."]
