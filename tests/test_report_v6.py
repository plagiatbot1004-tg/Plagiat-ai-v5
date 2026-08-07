from io import BytesIO

from pypdf import PdfReader

from app.services.ai_risk import AIStyleAssessment
from app.services.internal_similarity import (
    InternalMatch,
    InternalSource,
    MultiSourceResult,
)
from app.services.quetext import InternetScanResult, InternetSource
from app.services.report import build_report


def test_v6_report_hides_internal_database_evidence() -> None:
    internet = InternetScanResult(
        similarity=18.0,
        originality=82.0,
        sources=[
            InternetSource(
                title="Academic article",
                url="https://example.org/article",
                matched_words=18,
                introduction="Internetdan topilgan mos fragment.",
                input_offset=0,
                matched_text="Internetdan topilgan mos fragment.",
            )
        ],
        status="completed",
    )
    match = InternalMatch(
        source_document_id=7,
        source_label="PlagAI ichki hujjat #7",
        input_start=80,
        input_end=160,
        input_word_start=14,
        input_word_end=26,
        source_start=10,
        source_end=90,
        matched_words=12,
        text="Ichki hujjatdan topilgan o'xshash matn fragmenti.",
    )
    internal_source = InternalSource(
        document_id=7,
        label="PlagAI ichki hujjat #7",
        matched_words=12,
        similarity=12.0,
        matches=[match],
    )
    multi = MultiSourceResult(
        internet_similarity=18.0,
        internal_similarity=12.0,
        combined_similarity=30.0,
        combined_originality=70.0,
        internet_matched_words=18,
        internal_matched_words=12,
        deduplicated_matched_words=30,
        total_words=100,
        internal_sources=[internal_source],
    )
    ai = AIStyleAssessment(
        score=11.0,
        verdict="AIga o'xshash matn ulushi past",
        reasons=[],
        supported=True,
        language="uz",
        provider="PlagAI",
        confidence="past",
    )

    pdf = build_report(
        "test.docx",
        100,
        None,
        internet,
        ai,
        [],
        multi,
    )
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert "V6 MULTI-SOURCE" in text
    assert "UMUMIY O‘XSHASHLIK" in text
    assert "30.00%" in text
    assert "PlagAI ichki hujjat #7" not in text
    assert "Ichki hujjatdan topilgan" not in text


def test_v6_report_paginates_very_long_evidence_without_losing_the_tail() -> None:
    long_internet_fragment = (
        "INTERNET_BOSHI " + ("uzun internet fragmenti " * 1800) + "INTERNET_OXIRI"
    )
    long_internal_fragment = "ICHKI_BOSHI " + ("uzun ichki fragment " * 1800) + "ICHKI_OXIRI"
    internet = InternetScanResult(
        similarity=55.0,
        originality=45.0,
        sources=[
            InternetSource(
                title="Long source",
                url="https://example.org/long",
                matched_words=3600,
                introduction=long_internet_fragment,
            )
        ],
        status="completed",
    )
    internal_match = InternalMatch(
        source_document_id=9,
        source_label="PlagAI ichki hujjat #9",
        input_start=0,
        input_end=len(long_internal_fragment),
        input_word_start=0,
        input_word_end=3600,
        source_start=0,
        source_end=len(long_internal_fragment),
        matched_words=3600,
        text=long_internal_fragment,
    )
    internal_source = InternalSource(
        document_id=9,
        label="PlagAI ichki hujjat #9",
        matched_words=3600,
        similarity=55.0,
        matches=[internal_match],
    )
    multi = MultiSourceResult(
        internet_similarity=55.0,
        internal_similarity=55.0,
        combined_similarity=55.0,
        combined_originality=45.0,
        internet_matched_words=3600,
        internal_matched_words=3600,
        deduplicated_matched_words=3600,
        total_words=6500,
        internal_sources=[internal_source],
    )

    pdf = build_report(
        "very-long.docx",
        6500,
        internet_result=internet,
        multi_source_result=multi,
    )
    reader = PdfReader(BytesIO(pdf))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)

    assert len(reader.pages) > 2
    assert "INTERNET_BOSHI" in text
    assert "INTERNET_OXIRI" in text
    assert "ICHKI_BOSHI" not in text
    assert "ICHKI_OXIRI" not in text
    assert "davomi" in text
