from io import BytesIO

import pytest
from pypdf import PdfReader

from app.services.ai_risk import AIStyleAssessment
from app.services.quetext import InternetScanResult, InternetSource
from app.services.report import build_report


def _completed_result() -> InternetScanResult:
    return InternetScanResult(
        similarity=24.5,
        originality=75.5,
        sources=[
            InternetSource("Ochiq manba", "https://example.uz", 31),
        ],
        status="completed",
    )


def test_v6_pdf_contains_completed_multisource_sections() -> None:
    ai_assessment = AIStyleAssessment(
        score=38,
        verdict="Natija noaniq - qo‘shimcha mualliflik tekshiruvi kerak",
        reasons=["Gap tuzilishida bir xillik kuzatildi."],
        language="uz",
        provider="PlagiAI stilometriyasi",
    )
    report = build_report(
        "v6.docx",
        500,
        internet_result=_completed_result(),
        ai_assessment=ai_assessment,
        authorship_questions=["Asosiy xulosani tushuntiring."],
    )

    assert report.startswith(b"%PDF")
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(report)).pages)
    normalized = " ".join(text.split())
    assert "V6 MULTI-SOURCE" in text
    assert "Quetext DeepSearch" in text
    assert "UMUMIY ORIGINALLIK" in text
    assert "PLAGAI ICHKI BAZA" not in text
    assert "PlagAI ichki hujjatlar bazasi" not in text
    assert "Takrorlanmaydigan mos so‘zlar" not in text
    assert "Internet tekshiruvi yakunlanmadi" not in normalized


def test_failed_or_pending_scan_cannot_generate_pdf() -> None:
    for status in ("failed", "pending", "disabled"):
        internet = InternetScanResult(
            similarity=None,
            originality=None,
            status=status,
            error_message="Insufficient credits",
        )
        with pytest.raises(ValueError, match="faqat muvaffaqiyatli"):
            build_report("xato.docx", 1200, internet_result=internet)
