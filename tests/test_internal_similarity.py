from app.services.internal_similarity import (
    InternalDocument,
    combine_similarity_results,
    scan_internal_documents,
)
from app.services.quetext import InternetSource


def test_internal_scan_finds_copy_and_deduplicates_two_sources() -> None:
    copied = (
        "ta'lim sifatini oshirish uchun zamonaviy pedagogik texnologiyalar "
        "va mustaqil tahlil usullari muntazam qo'llaniladi"
    )
    current = f"Kirish qismi boshqacha yozilgan. {copied}. Yakuniy xulosa ham yangi."
    candidates = [
        InternalDocument(1, 20, "first.docx", f"Muqaddima. {copied}. Davomi."),
        InternalDocument(2, 30, "second.docx", f"Boshqa matn. {copied}. Tugadi."),
    ]

    result = scan_internal_documents(
        current_document_id=99,
        current_user_id=10,
        current_text=current,
        candidates=candidates,
    )

    assert len(result.sources) == 2
    assert result.matched_words >= 12
    assert result.matched_words < sum(source.matched_words for source in result.sources)
    assert result.sources[0].label.startswith("PlagAI ichki hujjat #")


def test_internal_scan_normalizes_uzbek_cyrillic_and_latin() -> None:
    current = (
        "O‘zbekiston ta’lim tizimida o‘quvchilarning mustaqil fikrlashi va "
        "ilmiy izlanish olib borishi muhim ahamiyat kasb etadi."
    )
    source = (
        "Ўзбекистон таълим тизимида ўқувчиларнинг мустақил фикрлаши ва "
        "илмий изланиш олиб бориши муҳим аҳамият касб этади."
    )
    result = scan_internal_documents(
        current_document_id=9,
        current_user_id=1,
        current_text=current,
        candidates=[InternalDocument(4, 2, "source.txt", source)],
    )

    assert result.similarity > 80
    assert result.sources[0].matched_words >= 12


def test_own_previous_document_keeps_filename() -> None:
    text = "bir ikki uch to'rt besh olti yetti sakkiz to'qqiz o'n o'n bir o'n ikki"
    result = scan_internal_documents(
        current_document_id=8,
        current_user_id=55,
        current_text=text,
        candidates=[InternalDocument(7, 55, "mening-ishim.docx", text)],
    )

    assert result.sources[0].label == "mening-ishim.docx"
    assert result.similarity == 100.0


def test_combined_score_does_not_double_count_same_passage() -> None:
    text = " ".join(f"word{index}" for index in range(100))
    copied_text = " ".join(f"word{index}" for index in range(20, 40))
    offset = text.index("word20")
    internal = scan_internal_documents(
        current_document_id=2,
        current_user_id=1,
        current_text=text,
        candidates=[InternalDocument(1, 2, "private.docx", copied_text)],
    )
    internet_sources = [
        InternetSource(
            title="Web source",
            url="https://example.com",
            matched_words=20,
            similarity=100,
            input_offset=offset,
            matched_text=copied_text,
        )
    ]

    combined = combine_similarity_results(
        current_text=text,
        internet_similarity=20.0,
        internet_sources=internet_sources,
        internal=internal,
    )

    assert combined.internal_similarity == 20.0
    assert combined.combined_similarity == 20.0
    assert combined.deduplicated_matched_words == 20


def test_combined_score_adds_non_overlapping_internal_evidence() -> None:
    text = " ".join(f"word{index}" for index in range(100))
    internal_text = " ".join(f"word{index}" for index in range(50, 70))
    internet_text = " ".join(f"word{index}" for index in range(20))
    internal = scan_internal_documents(
        current_document_id=2,
        current_user_id=1,
        current_text=text,
        candidates=[InternalDocument(1, 2, "private.docx", internal_text)],
    )
    combined = combine_similarity_results(
        current_text=text,
        internet_similarity=20.0,
        internet_sources=[
            InternetSource(
                title="Web",
                url="https://example.com",
                matched_words=20,
                input_offset=0,
                matched_text=internet_text,
            )
        ],
        internal=internal,
    )

    assert combined.combined_similarity == 40.0
    assert combined.combined_originality == 60.0
