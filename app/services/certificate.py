import json
import base64
import os
import secrets
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from html import escape as html_escape
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlencode

from reportlab.graphics.barcode import qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Certificate, ExternalScan, Submission, User

NAVY = colors.HexColor("#123B5D")
TURQUOISE = colors.HexColor("#1F8E8A")
GOLD = colors.HexColor("#B88A3B")
GREEN = colors.HexColor("#2E6D54")
SLATE = colors.HexColor("#384A55")
MUTED = colors.HexColor("#6C7A80")
BORDER = colors.HexColor("#D8D2C4")
PAPER = colors.HexColor("#FFFEF8")
PALE_TURQUOISE = colors.HexColor("#F0F8F6")
PALE_GOLD = colors.HexColor("#FBF7EC")


@lru_cache(maxsize=1)
def _brand_logo_bytes() -> bytes | None:
    """Load the official PLAG AI UZ logo without making it a hard runtime dependency."""
    override = os.getenv("PLAGIAI_LOGO_FILE", "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return path.read_bytes()

    encoded_path = Path(__file__).resolve().parents[1] / "assets" / "plagai_logo.png.b64"
    if not encoded_path.is_file():
        return None
    try:
        return base64.b64decode(encoded_path.read_text(encoding="ascii"), validate=True)
    except (OSError, ValueError):
        return None


def _brand_logo_flowable(max_width: float = 44 * mm) -> RLImage | None:
    logo = _brand_logo_bytes()
    if not logo:
        return None
    image = RLImage(BytesIO(logo))
    scale = max_width / image.imageWidth
    image.drawWidth = max_width
    image.drawHeight = image.imageHeight * scale
    return image


def _fonts() -> tuple[str, str, str]:
    regular_paths = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    )
    bold_paths = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    )
    display_paths = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf"),
    )
    regular = "Helvetica"
    bold = "Helvetica-Bold"
    display = bold
    for path in regular_paths:
        if path.exists():
            if "PlagiAI-Cert-Regular" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PlagiAI-Cert-Regular", str(path)))
            regular = "PlagiAI-Cert-Regular"
            break
    for path in bold_paths:
        if path.exists():
            if "PlagiAI-Cert-Bold" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PlagiAI-Cert-Bold", str(path)))
            bold = "PlagiAI-Cert-Bold"
            break
    for path in display_paths:
        if path.exists():
            if "PlagiAI-Cert-Display" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PlagiAI-Cert-Display", str(path)))
            display = "PlagiAI-Cert-Display"
            break
    return regular, bold, display


def _draw_step_motif(canvas, x: float, y: float, size: float) -> None:
    """Minimal stepped textile motif with no star-shaped geometry."""
    canvas.saveState()
    canvas.translate(x, y)
    canvas.setLineWidth(0.45)
    canvas.setStrokeColor(TURQUOISE)
    upper = canvas.beginPath()
    upper.moveTo(-size, 0)
    upper.lineTo(-size * 0.5, size * 0.34)
    upper.lineTo(0, 0)
    upper.lineTo(size * 0.5, size * 0.34)
    upper.lineTo(size, 0)
    canvas.drawPath(upper, stroke=1, fill=0)
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.32)
    lower = canvas.beginPath()
    lower.moveTo(-size * 0.72, -size * 0.27)
    lower.lineTo(-size * 0.34, -size * 0.04)
    lower.lineTo(0, -size * 0.27)
    lower.lineTo(size * 0.34, -size * 0.04)
    lower.lineTo(size * 0.72, -size * 0.27)
    canvas.drawPath(lower, stroke=1, fill=0)
    canvas.restoreState()


def _decorate_certificate(canvas, _doc, page_size: tuple[float, float]) -> None:
    width, height = page_size
    canvas.saveState()
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)

    # Double print-style frame: restrained, formal and easy to reproduce on paper.
    canvas.setStrokeColor(NAVY)
    canvas.setLineWidth(0.9)
    canvas.rect(6 * mm, 6 * mm, width - 12 * mm, height - 12 * mm, stroke=1, fill=0)
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.35)
    canvas.rect(8.2 * mm, 8.2 * mm, width - 16.4 * mm, height - 16.4 * mm, stroke=1, fill=0)

    # A narrow stepped textile-style frieze gives Uzbek character while staying
    # formal and deliberately avoiding star-shaped ornaments.
    y_top = height - 11.8 * mm
    y_bottom = 11.8 * mm
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.35)
    canvas.line(17 * mm, y_top, width - 17 * mm, y_top)
    canvas.line(17 * mm, y_bottom, width - 17 * mm, y_bottom)
    step = 16 * mm
    x = 20 * mm
    while x <= width - 20 * mm:
        _draw_step_motif(canvas, x, y_top, 2.5 * mm)
        _draw_step_motif(canvas, x, y_bottom, 2.5 * mm)
        x += step

    # Small matching corner marks; no rosettes or stars.
    _draw_step_motif(canvas, 11.2 * mm, height - 11.2 * mm, 2.6 * mm)
    _draw_step_motif(canvas, width - 11.2 * mm, height - 11.2 * mm, 2.6 * mm)
    _draw_step_motif(canvas, 11.2 * mm, 11.2 * mm, 2.6 * mm)
    _draw_step_motif(canvas, width - 11.2 * mm, 11.2 * mm, 2.6 * mm)
    canvas.restoreState()


def _source_count(raw: str) -> int:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return 0
    return len(data) if isinstance(data, list) else 0


def _certificate_number() -> str:
    return f"PLA-{datetime.now(UTC):%Y}-{uuid.uuid4().hex[:12].upper()}"


def verification_url(settings: Settings, certificate: Certificate) -> str:
    query = urlencode({"token": certificate.verification_token})
    number = quote(certificate.certificate_number, safe="")
    return f"{settings.verification_base_url}/verify/{number}?{query}"


def _qr_drawing(value: str, size: float = 31 * mm) -> Drawing:
    widget = qr.QrCodeWidget(value)
    x1, y1, x2, y2 = widget.getBounds()
    width = x2 - x1
    height = y2 - y1
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    return drawing


def build_certificate_pdf(certificate: Certificate, verify_url: str) -> bytes:
    regular, bold, display = _fonts()
    buffer = BytesIO()
    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=17 * mm,
        title=f"PlagiAI sertifikat {certificate.certificate_number}",
        author="PlagiAI",
        subject="Hujjat tekshiruvi sertifikati",
    )
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "CertTitle",
        parent=base["Title"],
        fontName=display,
        fontSize=21,
        leading=24,
        textColor=NAVY,
        alignment=TA_CENTER,
        spaceAfter=2 * mm,
    )
    subtitle = ParagraphStyle(
        "CertSubtitle",
        parent=base["BodyText"],
        fontName=regular,
        fontSize=9,
        leading=12.5,
        textColor=SLATE,
        alignment=TA_CENTER,
    )
    heading = ParagraphStyle(
        "CertHeading",
        parent=base["Heading2"],
        fontName=bold,
        fontSize=8.4,
        leading=12,
        textColor=NAVY,
        alignment=TA_LEFT,
    )
    body = ParagraphStyle(
        "CertBody",
        parent=base["BodyText"],
        fontName=regular,
        fontSize=8.1,
        leading=10.6,
        textColor=SLATE,
    )
    body_bold = ParagraphStyle(
        "CertBodyBold",
        parent=body,
        fontName=bold,
        textColor=NAVY,
    )
    small = ParagraphStyle(
        "CertSmall",
        parent=body,
        fontSize=6.8,
        leading=8.5,
        textColor=MUTED,
    )
    metric_value = ParagraphStyle(
        "CertMetricValue",
        parent=body,
        fontName=display,
        fontSize=18.5,
        leading=21,
        textColor=NAVY,
        alignment=TA_CENTER,
    )
    metric_label = ParagraphStyle(
        "CertMetricLabel",
        parent=small,
        alignment=TA_CENTER,
    )

    status_text = "AMALDA" if certificate.status == "active" else certificate.status.upper()
    ai_text = (
        "Baholanmagan"
        if certificate.ai_style_score is None
        else f"{certificate.ai_style_score:.2f}%"
    )
    issued = certificate.issued_at.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    recipient = certificate.recipient_name.strip() or "Telegram foydalanuvchisi"
    brand_logo = _brand_logo_flowable()
    brand_cell = brand_logo or Paragraph(
        "<b>PLAG AI UZ</b><br/><font size='7'>AKADEMIK HALOLLIK TIZIMI</font>",
        body_bold,
    )

    story = [
        Table(
            [[
                brand_cell,
                Paragraph("O‘ZBEKISTON  •  ELEKTRON HUJJAT", small),
                Paragraph(
                    f"HOLATI: <b>{status_text}</b><br/>"
                    f"SERTIFIKAT № <b>{html_escape(certificate.certificate_number)}</b>",
                    body_bold,
                ),
            ]],
            colWidths=[74 * mm, 72 * mm, 115 * mm],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.7, GOLD),
            ]),
        ),
        Spacer(1, 4 * mm),
        Paragraph("HUJJAT TEKSHIRUVI SERTIFIKATI", title),
        Paragraph(
            "Mazkur sertifikat quyida ko‘rsatilgan hujjat PlagiAI tizimida tashqi manbalar "
            "bo‘yicha tekshiruvdan o‘tkazilganini va tekshiruv natijalari elektron qayd "
            "etilganini tasdiqlaydi.",
            subtitle,
        ),
        Spacer(1, 3.5 * mm),
    ]

    metrics = Table(
        [[
            Paragraph(f"{certificate.originality_score:.2f}%", metric_value),
            Paragraph(f"{certificate.similarity_score:.2f}%", metric_value),
            Paragraph(str(certificate.source_count), metric_value),
            Paragraph(ai_text, metric_value),
        ], [
            Paragraph("ORIGINALLIK", metric_label),
            Paragraph("O‘XSHASHLIK", metric_label),
            Paragraph("MANBALAR", metric_label),
            Paragraph("AI EHTIMOLI", metric_label),
        ]],
        colWidths=[65.25 * mm] * 4,
        rowHeights=[13 * mm, 6.5 * mm],
    )
    metrics.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
        ("LINEABOVE", (0, 0), (-1, 0), 0.85, NAVY),
        ("LINEBELOW", (0, -1), (-1, -1), 0.85, NAVY),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, GOLD),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.extend([metrics, Spacer(1, 4 * mm)])

    details = Table(
        [
            [Paragraph("Hujjat", heading), Paragraph(html_escape(certificate.document_name), body_bold)],
            [Paragraph("Qabul qiluvchi", heading), Paragraph(html_escape(recipient), body)],
            [Paragraph("So‘zlar soni", heading), Paragraph(f"{certificate.word_count:,}", body)],
            [Paragraph("Tekshiruv provayderi", heading), Paragraph(html_escape(certificate.provider), body)],
            [Paragraph("Berilgan vaqt", heading), Paragraph(issued, body)],
            [Paragraph("SHA-256", heading), Paragraph(html_escape(certificate.document_hash), small)],
        ],
        colWidths=[40 * mm, 112 * mm],
    )
    details.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PALE_GOLD),
        ("BOX", (0, 0), (-1, -1), 0.55, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))

    qr_block = Table(
        [[_qr_drawing(verify_url), Paragraph(
            "<b>RAQAMLI TASDIQLASH</b><br/>QR kod sertifikatning jonli verifikatsiya sahifasini ochadi. "
            "Sahifadagi ID, hujjat xeshi va natijalar ushbu PDF bilan mos bo‘lishi kerak.<br/><br/>"
            f"<font size='6'>{html_escape(verify_url)}</font>",
            body,
        )]],
        colWidths=[36 * mm, 72 * mm],
    )
    qr_block.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_TURQUOISE),
        ("BOX", (0, 0), (-1, -1), 0.65, TURQUOISE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))

    content = Table([[details, qr_block]], colWidths=[153 * mm, 108 * mm])
    content.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([content, Spacer(1, 3.5 * mm)])

    disclaimer = Table([[Paragraph(
        "<b>Muhim:</b> O‘xshashlik foizi plagiat bo‘yicha yakuniy akademik hukm emas. "
        "Sertifikat faqat tekshiruv o‘tkazilganini va provayder qaytargan natijani qayd etadi. "
        "Iqtiboslar, bibliografiya, kontekst va akademik qoidalar ekspert tomonidan alohida baholanadi.",
        small,
    )]], colWidths=[261 * mm])
    disclaimer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_GOLD),
        ("LINEABOVE", (0, 0), (-1, -1), 0.55, GOLD),
        ("LINEBELOW", (0, 0), (-1, -1), 0.55, GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))
    story.append(disclaimer)

    decorate = lambda canvas, built_doc: _decorate_certificate(canvas, built_doc, page_size)
    doc.build(story, onFirstPage=decorate)
    return buffer.getvalue()


async def get_or_create_certificate(
    *,
    session_maker: async_sessionmaker[AsyncSession],
    submission: Submission,
    external: ExternalScan,
    telegram_id: int,
    settings: Settings,
) -> tuple[Certificate, bytes, str]:
    if external.status != "completed":
        raise ValueError("Sertifikat faqat yakunlangan tekshiruv uchun beriladi.")
    if external.internet_similarity is None or external.internet_originality is None:
        raise ValueError("Yakuniy Quetext foizlari mavjud emas; sertifikat berilmadi.")

    async with session_maker() as session:
        certificate = await session.scalar(
            select(Certificate).where(Certificate.submission_id == submission.id)
        )
        if certificate is None:
            user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
            recipient_name = ""
            if user is not None:
                recipient_name = " ".join(
                    item.strip() for item in (user.first_name, user.last_name or "") if item.strip()
                )
            certificate = Certificate(
                submission_id=submission.id,
                certificate_number=_certificate_number(),
                verification_token=secrets.token_urlsafe(32),
                status="active",
                recipient_name=recipient_name,
                document_name=submission.filename,
                document_hash=submission.content_hash,
                word_count=submission.word_count,
                similarity_score=float(external.internet_similarity),
                originality_score=float(external.internet_originality),
                source_count=_source_count(external.internet_sources_json),
                provider="Quetext DeepSearch",
                ai_style_score=external.ai_style_score,
                issued_at=datetime.now(UTC),
            )
            session.add(certificate)
            await session.commit()
            await session.refresh(certificate)

    url = verification_url(settings, certificate)
    pdf = build_certificate_pdf(certificate, url)
    return certificate, pdf, url
