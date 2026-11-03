"""Text clean-up and chunking.

Kokoro runs one chunk per CPU core at a time, so a long text is cut into chunks at sentence ends (or, for a very long
sentence, at commas, then at spaces) and the chunks are read in parallel. Each chunk remembers the pause that
follows it, so the joined audio breathes where the text does.
"""

import re
import unicodedata
from dataclasses import dataclass

# Pauses between chunks, in seconds. Kokoro uses the same sentence and clause pauses inside a chunk.
PARAGRAPH_PAUSE = 0.6
SENTENCE_PAUSE = 0.25
CLAUSE_PAUSE = 0.1

# A chunk never grows past this, so one long chunk can't keep the other cores idle.
MAX_CHUNK = 300
# ...and doesn't shrink below this, so prosody has room to settle.
MIN_CHUNK = 80

_SENTENCE_END = re.compile(r"(?<=[.!?…。！？])[\"'”’)\]]*\s+")
_CLAUSE_END = re.compile(r"(?<=[,;:—–])\s+")
_SPEAKABLE = re.compile(r"[A-Za-z0-9À-ɏऀ-ॿ]")


@dataclass(frozen=True)
class Chunk:
    text: str
    # Silence after this chunk, in seconds. The last chunk has none.
    pause: float


def normalize(text: str) -> str:
    """NFC, no control characters, single spaces inside lines, at most one blank line between paragraphs."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or not unicodedata.category(ch).startswith("C"))
    lines = [" ".join(line.split()) for line in text.split("\n")]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def speakable(text: str) -> bool:
    """Whether the text has at least one letter or digit Kokoro can read (the schema's pattern checks the same)."""
    return _SPEAKABLE.search(text) is not None


def chunk(text: str, workers: int = 1) -> list[Chunk]:
    """Cuts normalized text into chunks of about len(text) / workers characters, at natural breaks."""
    target = max(MIN_CHUNK, min(MAX_CHUNK, -(-len(text) // max(1, workers))))
    chunks: list[Chunk] = []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    for p_index, paragraph in enumerate(paragraphs):
        pieces = _pieces(paragraph.replace("\n", " "))
        current = ""
        for piece_text, piece_pause in pieces:
            if current and len(current) + 1 + len(piece_text) > target:
                chunks.append(Chunk(current, last_pause))
                current = piece_text
            else:
                current = f"{current} {piece_text}" if current else piece_text
            last_pause = piece_pause
        if current:
            pause = PARAGRAPH_PAUSE if p_index < len(paragraphs) - 1 else 0.0
            chunks.append(Chunk(current, pause))
    if chunks:
        chunks[-1] = Chunk(chunks[-1].text, 0.0)
    return [c for c in chunks if speakable(c.text)] or chunks[:1]


def _pieces(paragraph: str) -> list[tuple[str, float]]:
    """Sentences, with any sentence longer than MAX_CHUNK cut at clauses and then at spaces."""
    pieces: list[tuple[str, float]] = []
    for sentence in (s for s in _SENTENCE_END.split(paragraph) if s.strip()):
        if len(sentence) <= MAX_CHUNK:
            pieces.append((sentence, SENTENCE_PAUSE))
            continue
        for clause in (c for c in _CLAUSE_END.split(sentence) if c.strip()):
            for part in _wrap(clause, MAX_CHUNK):
                pieces.append((part, CLAUSE_PAUSE))
        pieces[-1] = (pieces[-1][0], SENTENCE_PAUSE)
    return pieces


def _wrap(text: str, width: int) -> list[str]:
    """Cuts text at spaces into parts of at most `width` characters (a single longer word stays whole)."""
    parts: list[str] = []
    current = ""
    for word in text.split(" "):
        if current and len(current) + 1 + len(word) > width:
            parts.append(current)
            current = word
        else:
            current = f"{current} {word}" if current else word
    if current:
        parts.append(current)
    return parts
