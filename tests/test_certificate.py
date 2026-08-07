from datetime import UTC, datetime

from app.config import Settings
from app.models import Certificate
from app.services.certificate import build_certificate_pdf, verification_url


def _certificate() -> Certificate:
    return Certificate(
        submission_id=1,
        certificate_number="PLA-2026-TEST12345678",
        verification_token="abcdefghijklmnopqrstuvwxyz1234567890",
        status="active",
        recipient_name="Test User",
        document_name="test.pdf",
        document_hash="a" * 64,
        word_count=1234,
        similarity_score=12.4,
        originality_score=87.6,
        source_count=3,
        provider="Quetext DeepSearch",
        ai_style_score=10.0,
        issued_at=datetime.now(UTC),
    )


def test_certificate_pdf_is_generated() -> None:
    certificate = _certificate()
    pdf = build_certificate_pdf(
        certificate,
        "https://example.com/verify/PLA-2026-TEST12345678?token=abcdefghijklmnopqrstuvwxyz1234567890",
    )
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 10_000


def test_verification_url_uses_public_base_url() -> None:
    settings = Settings(
        BOT_TOKEN="123456789:abcdefghijklmnopqrstuvwxyzABCDEFGHI",
        PUBLIC_BASE_URL="https://plagiai.example.com/",
    )
    url = verification_url(settings, _certificate())
    assert url.startswith("https://plagiai.example.com/verify/PLA-2026-TEST12345678?")
    assert "token=" in url
