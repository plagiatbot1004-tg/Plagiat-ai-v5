import json
import secrets
import uuid
from datetime import UTC, datetime
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
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models import Certificate, ExternalScan, Submission, User

NAVY = colors.HexColor("#0B1F3A")
BLUE = colors.HexColor("#1D4ED8")
CYAN = colors.HexColor("#0891B2")
GREEN = colors.HexColor("#15803D")
SLATE = colors.HexColor("#475569")
MUTED = colors.HexColor("#64748B")
BORDER = colors.HexColor("#CBD5E1")
PALE_BLUE = colors.HexColor("#EFF6FF")
PALE_GREEN = colors.HexColor("#ECFDF5")
PALE_SLATE = colors.HexColor("#F8FAFC")


def _fonts() -> tuple[str, str]:
    regular_paths = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
    )
    bold_paths = (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    )
    regular = "Helvetica"
    bold = "Helvetica-Bold"
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
    return regular, bold


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
    regular, bold = _fonts()
    buffer = BytesIO()
    page_size = landscape(A4)
    doc = SimpleDocTemplate(
        buffer,
        pagesize=page_size,
        leftMargin=13 * mm,
        rightMargin=13 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title=f"PlagiAI sertifikat {certificate.certificate_number}",
        author="PlagiAI",
        subject="Hujjat tekshiruvi sertifikati",
    )
    base = getSampleStyleSheet()
    title = ParagraphStyle(
        "CertTitle",
        parent=base["Title"],
        fontName=bold,
        fontSize=22,
        leading=25,
        textColor=NAVY,
        alignment=TA_CENTER,
        spaceAfter=2 * mm,
    )
    subtitle = ParagraphStyle(
        "CertSubtitle",
        parent=base["BodyText"],
        fontName=regular,
        fontSize=9.5,
        leading=13,
        textColor=SLATE,
        alignment=TA_CENTER,
    )
    heading = ParagraphStyle(
        "CertHeading",
        parent=base["Heading2"],
        fontName=bold,
        fontSize=10,
        leading=12,
        textColor=NAVY,
        alignment=TA_LEFT,
    )
    body = ParagraphStyle(
        "CertBody",
        parent=base["BodyText"],
        fontName=regular,
        fontSize=8.3,
        leading=11,
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
        fontName=bold,
        fontSize=20,
        leading=22,
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

    story = [
        Table(
            [[
                Paragraph("<b>PLAGIAI</b><br/><font size='7'>ACADEMIC INTEGRITY</font>", subtitle),
                Paragraph(f"<b>{status_text}</b>", body_bold),
                Paragraph(f"ID: <b>{html_escape(certificate.certificate_number)}</b>", body_bold),
            ]],
            colWidths=[85 * mm, 45 * mm, 130 * mm],
        ),
        Spacer(1, 5 * mm),
        Paragraph("HUJJAT TEKSHIRUVI SERTIFIKATI", title),
        Paragraph(
            "Ushbu sertifikat ko‘rsatilgan hujjat PlagiAI orqali tashqi manbalar bo‘yicha "
            "tekshiruvdan o‘tkazilganini va quyidagi natija qayd etilganini tasdiqlaydi.",
            subtitle,
        ),
        Spacer(1, 5 * mm),
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
        colWidths=[60 * mm] * 4,
        rowHeights=[14 * mm, 7 * mm],
    )
    metrics.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.8, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.extend([metrics, Spacer(1, 5 * mm)])

    details = Table(
        [
            [Paragraph("Hujjat", heading), Paragraph(html_escape(certificate.document_name), body_bold)],
            [Paragraph("Qabul qiluvchi", heading), Paragraph(html_escape(recipient), body)],
            [Paragraph("So‘zlar soni", heading), Paragraph(f"{certificate.word_count:,}", body)],
            [Paragraph("Tekshiruv provayderi", heading), Paragraph(html_escape(certificate.provider), body)],
            [Paragraph("Berilgan vaqt", heading), Paragraph(issued, body)],
            [Paragraph("SHA-256", heading), Paragraph(html_escape(certificate.document_hash), small)],
        ],
        colWidths=[48 * mm, 147 * mm],
    )
    details.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), PALE_SLATE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
    ]))

    qr_block = Table(
        [[_qr_drawing(verify_url), Paragraph(
            "<b>QR orqali tekshirish</b><br/>QR kod sertifikatning jonli verifikatsiya sahifasini ochadi. "
            "Sahifadagi ID, hujjat xeshi va natijalar ushbu PDF bilan mos bo‘lishi kerak.<br/><br/>"
            f"<font size='6'>{html_escape(verify_url)}</font>",
            body,
        )]],
        colWidths=[38 * mm, 67 * mm],
    )
    qr_block.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_GREEN),
        ("BOX", (0, 0), (-1, -1), 0.8, GREEN),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))

    content = Table([[details, qr_block]], colWidths=[198 * mm, 108 * mm])
    content.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([content, Spacer(1, 4 * mm)])

    disclaimer = Table([[Paragraph(
        "<b>Muhim:</b> O‘xshashlik foizi plagiat bo‘yicha yakuniy akademik hukm emas. "
        "Sertifikat faqat tekshiruv o‘tkazilganini va provayder qaytargan natijani qayd etadi. "
        "Iqtiboslar, bibliografiya, kontekst va akademik qoidalar ekspert tomonidan alohida baholanadi.",
        small,
    )]], colWidths=[306 * mm])
    disclaimer.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE_SLATE),
        ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]))
    story.append(disclaimer)

    def decorate(canvas, _doc) -> None:
        width, height = page_size
        canvas.saveState()
        canvas.setStrokeColor(BLUE)
        canvas.setLineWidth(1.2)
        canvas.roundRect(7 * mm, 7 * mm, width - 14 * mm, height - 14 * mm, 4 * mm, stroke=1, fill=0)
        canvas.setStrokeColor(CYAN)
        canvas.setLineWidth(0.35)
        canvas.roundRect(9.5 * mm, 9.5 * mm, width - 19 * mm, height - 19 * mm, 3 * mm, stroke=1, fill=0)
        canvas.restoreState()

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
