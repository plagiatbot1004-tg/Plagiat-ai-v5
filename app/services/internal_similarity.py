from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

MIN_MATCH_WORDS = 8
_TOKEN_RE = re.compile(r"[^\W_]+(?:[\u2018\u2019\u02bb\u02bc'`-][^\W_]+)*", re.UNICODE)
_APOSTROPHES = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u02bb": "'",
        "\u02bc": "'",
        "`": "'",
    }
)
_CYRILLIC_TO_LATIN = str.maketrans(
    {
        "а": "a",
        "б": "b",
        "в": "v",
        "г": "g",
        "д": "d",
        "е": "e",
        "ё": "yo",
        "ж": "j",
        "з": "z",
        "и": "i",
        "й": "y",
        "к": "k",
        "л": "l",
        "м": "m",
        "н": "n",
        "о": "o",
        "п": "p",
        "р": "r",
        "с": "s",
        "т": "t",
        "у": "u",
        "ф": "f",
        "х": "x",
        "ц": "ts",
        "ч": "ch",
        "ш": "sh",
        "щ": "sh",
        "ъ": "'",
        "ы": "i",
        "ь": "",
        "э": "e",
        "ю": "yu",
        "я": "ya",
        "қ": "q",
        "ғ": "g'",
        "ҳ": "h",
        "ў": "o'",
    }
)


@dataclass(slots=True, frozen=True)
class WordToken:
    value: str
    start: int
    end: int


@dataclass(slots=True)
class InternalDocument:
    document_id: int
    owner_user_id: int
    filename: str
    text: str


@dataclass(slots=True)
class InternalMatch:
    source_document_id: int
    source_label: str
    input_start: int
    input_end: int
    input_word_start: int
    input_word_end: int
    source_start: int
    source_end: int
    matched_words: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_document_id": self.source_document_id,
            "source_label": self.source_label,
            "input_start": self.input_start,
            "input_end": self.input_end,
            "input_word_start": self.input_word_start,
            "input_word_end": self.input_word_end,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "matched_words": self.matched_words,
            "text": self.text,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> InternalMatch:
        return cls(
            source_document_id=int(value.get("source_document_id") or 0),
            source_label=str(value.get("source_label") or "PlagAI ichki hujjat"),
            input_start=int(value.get("input_start") or 0),
            input_end=int(value.get("input_end") or 0),
            input_word_start=int(value.get("input_word_start") or 0),
            input_word_end=int(value.get("input_word_end") or 0),
            source_start=int(value.get("source_start") or 0),
            source_end=int(value.get("source_end") or 0),
            matched_words=int(value.get("matched_words") or 0),
            text=str(value.get("text") or ""),
        )


@dataclass(slots=True)
class InternalSource:
    document_id: int
    label: str
    matched_words: int
    similarity: float
    matches: list[InternalMatch] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "label": self.label,
            "matched_words": self.matched_words,
            "similarity": self.similarity,
            "matches": [match.to_dict() for match in self.matches],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> InternalSource:
        matches = value.get("matches") if isinstance(value.get("matches"), list) else []
        return cls(
            document_id=int(value.get("document_id") or 0),
            label=str(value.get("label") or "PlagAI ichki hujjat"),
            matched_words=int(value.get("matched_words") or 0),
            similarity=float(value.get("similarity") or 0.0),
            matches=[InternalMatch.from_dict(item) for item in matches if isinstance(item, dict)],
        )


@dataclass(slots=True)
class InternalScanResult:
    similarity: float
    matched_words: int
    total_words: int
    sources: list[InternalSource] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "similarity": self.similarity,
            "matched_words": self.matched_words,
            "total_words": self.total_words,
            "sources": [source.to_dict() for source in self.sources],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> InternalScanResult:
        sources = value.get("sources") if isinstance(value.get("sources"), list) else []
        return cls(
            similarity=float(value.get("similarity") or 0.0),
            matched_words=int(value.get("matched_words") or 0),
            total_words=int(value.get("total_words") or 0),
            sources=[InternalSource.from_dict(item) for item in sources if isinstance(item, dict)],
        )


@dataclass(slots=True)
class MultiSourceResult:
    internet_similarity: float
    internal_similarity: float
    combined_similarity: float
    combined_originality: float
    internet_matched_words: int
    internal_matched_words: int
    deduplicated_matched_words: int
    total_words: int
    internal_sources: list[InternalSource] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "internet_similarity": self.internet_similarity,
            "internal_similarity": self.internal_similarity,
            "combined_similarity": self.combined_similarity,
            "combined_originality": self.combined_originality,
            "internet_matched_words": self.internet_matched_words,
            "internal_matched_words": self.internal_matched_words,
            "deduplicated_matched_words": self.deduplicated_matched_words,
            "total_words": self.total_words,
            "internal_sources": [source.to_dict() for source in self.internal_sources],
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> MultiSourceResult:
        sources = value.get("internal_sources")
        if not isinstance(sources, list):
            sources = []
        combined_similarity = min(
            100.0,
            max(0.0, float(value.get("combined_similarity") or 0.0)),
        )
        return cls(
            internet_similarity=float(value.get("internet_similarity") or 0.0),
            internal_similarity=float(value.get("internal_similarity") or 0.0),
            combined_similarity=combined_similarity,
            # Originality is derived from similarity so 0.0 is never mistaken
            # for a missing value and stale/inconsistent persisted values heal
            # automatically when an older scan is loaded.
            combined_originality=round(100.0 - combined_similarity, 2),
            internet_matched_words=int(value.get("internet_matched_words") or 0),
            internal_matched_words=int(value.get("internal_matched_words") or 0),
            deduplicated_matched_words=int(value.get("deduplicated_matched_words") or 0),
            total_words=int(value.get("total_words") or 0),
            internal_sources=[
                InternalSource.from_dict(item) for item in sources if isinstance(item, dict)
            ],
        )


def _normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(_APOSTROPHES).casefold()
    normalized = normalized.translate(_CYRILLIC_TO_LATIN)
    return normalized.strip("'-")


def tokenize_with_offsets(text: str) -> list[WordToken]:
    tokens: list[WordToken] = []
    for match in _TOKEN_RE.finditer(text):
        value = _normalize_token(match.group(0))
        if value:
            tokens.append(WordToken(value=value, start=match.start(), end=match.end()))
    return tokens


def _fingerprints(values: list[str], size: int) -> set[int]:
    if len(values) < size:
        return set()
    return {hash(tuple(values[index : index + size])) for index in range(len(values) - size + 1)}


def _word_union(intervals: Iterable[tuple[int, int]]) -> set[int]:
    result: set[int] = set()
    for start, end in intervals:
        if end > start:
            result.update(range(start, end))
    return result


def scan_internal_documents(
    *,
    current_document_id: int,
    current_user_id: int,
    current_text: str,
    candidates: Iterable[InternalDocument],
    min_match_words: int = MIN_MATCH_WORDS,
) -> InternalScanResult:
    """Find evidence-backed exact/normalized matches against prior submissions.

    Matching is word based, punctuation/case tolerant, and normalizes Uzbek Cyrillic
    and Latin spellings to the same comparison alphabet. The returned percentage is
    the union of matched input words, so one passage copied from several documents is
    counted only once.
    """
    current_tokens = tokenize_with_offsets(current_text)
    total_words = len(current_tokens)
    if total_words < min_match_words:
        return InternalScanResult(0.0, 0, total_words, [])

    current_values = [token.value for token in current_tokens]
    current_fingerprints = _fingerprints(current_values, min_match_words)
    all_intervals: list[tuple[int, int]] = []
    sources: list[InternalSource] = []

    for candidate in candidates:
        if candidate.document_id == current_document_id or not candidate.text.strip():
            continue
        source_tokens = tokenize_with_offsets(candidate.text)
        if len(source_tokens) < min_match_words:
            continue
        source_values = [token.value for token in source_tokens]
        if not current_fingerprints.intersection(_fingerprints(source_values, min_match_words)):
            continue

        matcher = SequenceMatcher(None, current_values, source_values, autojunk=True)
        blocks = [block for block in matcher.get_matching_blocks() if block.size >= min_match_words]
        if not blocks:
            continue

        label = (
            candidate.filename
            if candidate.owner_user_id == current_user_id
            else f"PlagAI ichki hujjat #{candidate.document_id}"
        )
        matches: list[InternalMatch] = []
        source_intervals: list[tuple[int, int]] = []
        for block in blocks:
            input_start = current_tokens[block.a].start
            input_end = current_tokens[block.a + block.size - 1].end
            source_start = source_tokens[block.b].start
            source_end = source_tokens[block.b + block.size - 1].end
            source_intervals.append((block.a, block.a + block.size))
            matches.append(
                InternalMatch(
                    source_document_id=candidate.document_id,
                    source_label=label,
                    input_start=input_start,
                    input_end=input_end,
                    input_word_start=block.a,
                    input_word_end=block.a + block.size,
                    source_start=source_start,
                    source_end=source_end,
                    matched_words=block.size,
                    text=current_text[input_start:input_end],
                )
            )

        matched_indexes = _word_union(source_intervals)
        matched_words = len(matched_indexes)
        if not matched_words:
            continue
        all_intervals.extend(source_intervals)
        sources.append(
            InternalSource(
                document_id=candidate.document_id,
                label=label,
                matched_words=matched_words,
                similarity=round(100.0 * matched_words / total_words, 2),
                matches=matches,
            )
        )

    overall_indexes = _word_union(all_intervals)
    sources.sort(key=lambda item: (item.matched_words, item.similarity), reverse=True)
    return InternalScanResult(
        similarity=round(100.0 * len(overall_indexes) / total_words, 2),
        matched_words=len(overall_indexes),
        total_words=total_words,
        sources=sources,
    )


def _indexes_for_char_span(tokens: list[WordToken], start: int, end: int) -> set[int]:
    if end <= start:
        return set()
    return {index for index, token in enumerate(tokens) if token.end > start and token.start < end}


def combine_similarity_results(
    *,
    current_text: str,
    internet_similarity: float,
    internet_sources: Iterable[Any],
    internal: InternalScanResult,
) -> MultiSourceResult:
    """Combine Internet and internal evidence without double-counting overlaps."""
    tokens = tokenize_with_offsets(current_text)
    total_words = len(tokens)
    internet_indexes: set[int] = set()
    positioned_matches = 0
    for source in internet_sources:
        offset = getattr(source, "input_offset", None)
        matched_text = str(getattr(source, "matched_text", "") or "")
        matched_words = int(getattr(source, "matched_words", 0) or 0)
        if offset is None:
            continue
        try:
            start = max(0, int(offset))
        except (TypeError, ValueError):
            continue
        if matched_text:
            indexes = _indexes_for_char_span(tokens, start, start + len(matched_text))
        else:
            first = next((i for i, token in enumerate(tokens) if token.end > start), None)
            indexes = (
                set(range(first, min(total_words, first + matched_words)))
                if first is not None and matched_words > 0
                else set()
            )
        if indexes:
            positioned_matches += 1
            internet_indexes.update(indexes)

    internal_indexes = {
        index
        for source in internal.sources
        for match in source.matches
        for index in range(match.input_word_start, match.input_word_end)
        if 0 <= index < total_words
    }

    internet_similarity = round(min(100.0, max(0.0, float(internet_similarity))), 2)
    internal_similarity = round(min(100.0, max(0.0, float(internal.similarity))), 2)
    if total_words <= 0:
        combined = max(internet_similarity, internal_similarity)
        internet_words = internal_words = deduplicated_words = 0
    elif positioned_matches:
        uncovered_internal = internal_indexes.difference(internet_indexes)
        uncovered_internal_percent = 100.0 * len(uncovered_internal) / total_words
        positioned_internet_percent = 100.0 * len(internet_indexes) / total_words
        combined = min(
            100.0,
            max(internet_similarity, positioned_internet_percent) + uncovered_internal_percent,
        )
        internet_words = max(
            len(internet_indexes),
            round(total_words * internet_similarity / 100.0),
        )
        internal_words = len(internal_indexes)
        deduplicated_words = min(total_words, round(total_words * combined / 100.0))
    else:
        # Without Quetext offsets we cannot prove that Internet and internal spans
        # are separate, so use the conservative maximum instead of inflating score.
        combined = max(internet_similarity, internal_similarity)
        internet_words = round(total_words * internet_similarity / 100.0)
        internal_words = len(internal_indexes)
        deduplicated_words = round(total_words * combined / 100.0)

    combined = round(combined, 2)
    return MultiSourceResult(
        internet_similarity=internet_similarity,
        internal_similarity=internal_similarity,
        combined_similarity=combined,
        combined_originality=round(max(0.0, 100.0 - combined), 2),
        internet_matched_words=internet_words,
        internal_matched_words=internal_words,
        deduplicated_matched_words=deduplicated_words,
        total_words=total_words,
        internal_sources=internal.sources,
    )
