import hashlib
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.ai_risk import AIStyleAssessment, language_name
from app.services.assessment import build_professional_conclusion
from app.services.quetext import InternetScanResult

NAVY = colors.HexColor("#102A43")
GREEN = colors.HexColor("#15803D")
AMBER = colors.HexColor("#B45309")
SLATE = colors.HexColor("#475569")
MUTED = colors.HexColor("#64748B")
BORDER = colors.HexColor("#D8E1EA")
PALE_BLUE = colors.HexColor("#EFF6FF")
PALE_GREEN = colors.HexColor("#ECFDF3")
PALE_RED = colors.HexColor("#FEF3F2")
PALE_AMBER = colors.HexColor("#FFF7ED")
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
            if "PlagiAI-Regular" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PlagiAI-Regular", str(path)))
            regular = "PlagiAI-Regular"
            break
    for path in bold_paths:
        if path.exists():
            if "PlagiAI-Bold" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PlagiAI-Bold", str(path)))
            bold = "PlagiAI-Bold"
            break
    return regular, bold


def _styles(regular: str, bold: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName=regular,
            fontSize=8.2,
            leading=11.4,
            textColor=SLATE,
            spaceAfter=0.25 * mm,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName=regular,
            fontSize=7,
            leading=9,
            textColor=MUTED,
        ),
        "title": ParagraphStyle(
            "ReportTitle",
            parent=base["Title"],
            fontName=bold,
            fontSize=16.5,
            leading=19,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=1.2 * mm,
        ),
        "subtitle": ParagraphStyle(
            "Subtitle",
            parent=base["BodyText"],
            fontName=regular,
            fontSize=8.5,
            leading=11,
            textColor=MUTED,
            spaceAfter=3 * mm,
        ),
        "heading": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading2"],
            fontName=bold,
            fontSize=11.3,
            leading=13.2,
            textColor=NAVY,
            spaceBefore=1.2 * mm,
            spaceAfter=0.7 * mm,
            keepWithNext=True,
        ),
        "metric_value": ParagraphStyle(
            "MetricValue",
            parent=base["BodyText"],
            fontName=bold,
            fontSize=14,
            leading=16,
            textColor=NAVY,
            alignment=TA_CENTER,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            parent=base["BodyText"],
            fontName=regular,
            fontSize=6.8,
            leading=9,
            textColor=MUTED,
            alignment=TA_CENTER,
        ),
        "banner_title": ParagraphStyle(
            "BannerTitle",
            parent=base["BodyText"],
            fontName=bold,
            fontSize=10.5,
            leading=13,
            textColor=NAVY,
        ),
        "banner_body": ParagraphStyle(
            "BannerBody",
            parent=base["BodyText"],
            fontName=regular,
            fontSize=8,
            leading=10.5,
            textColor=SLATE,
        ),
        "table": ParagraphStyle(
            "TableText",
            parent=base["BodyText"],
            fontName=regular,
            fontSize=6.9,
            leading=8.8,
            textColor=SLATE,
        ),
        "table_bold": ParagraphStyle(
            "TableBold",
            parent=base["BodyText"],
            fontName=bold,
            fontSize=6.9,
            leading=8.8,
            textColor=NAVY,
        ),
    }


def _metric_card(
    value: str,
    label: str,
    styles: dict[str, ParagraphStyle],
    background: colors.Color,
) -> Table:
    card = Table(
        [
            [Paragraph(escape(value), styles["metric_value"])],
            [Paragraph(escape(label), styles["metric_label"])],
        ],
        colWidths=[56 * mm],
        rowHeights=[9 * mm, 6.5 * mm],
    )
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return card


def _report_id(filename: str, checked_at: datetime) -> str:
    source = f"{filename}|{checked_at.isoformat()}".encode()
    return hashlib.sha256(source).hexdigest()[:12].upper()


def _page_decorator(regular: str, bold: str, report_id: str):
    def draw(canvas, document) -> None:
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, height - 13 * mm, width - 18 * mm, height - 13 * mm)
        canvas.setFont(bold, 8)
        canvas.setFillColor(NAVY)
        canvas.drawString(18 * mm, height - 10 * mm, "PlagiAI PROFESSIONAL")
        canvas.setFont(regular, 7)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(width - 18 * mm, height - 10 * mm, f"Hisobot ID: {report_id}")
        canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
        canvas.drawString(18 * mm, 9 * mm, "Maxfiy • Akademik ekspertiza uchun")
        canvas.drawRightString(
            width - 18 * mm,
            9 * mm,
            f"V5.0 QUETEXT  |  {document.page}-sahifa",
        )
        canvas.restoreState()

    return draw


def build_report(
    filename: str,
    word_count: int,
    checked_at: datetime | None = None,
    internet_result: InternetScanResult | None = None,
    ai_assessment: AIStyleAssessment | None = None,
    authorship_questions: list[str] | None = None,
) -> bytes:
    if (
        internet_result is None
        or internet_result.status != "completed"
        or internet_result.similarity is None
        or internet_result.originality is None
    ):
        raise ValueError(
            "Yakuniy PDF faqat muvaffaqiyatli internet tekshiruvidan keyin yaratiladi."
        )

    checked_at = checked_at or datetime.now()
    regular, bold = _fonts()
    styles = _styles(regular, bold)
    conclusion = build_professional_conclusion(internet_result, ai_assessment)
    report_id = _report_id(filename, checked_at)
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=17 * mm,
        bottomMargin=16 * mm,
        title=f"PlagiAI professional hisoboti — {filename}",
        author="PlagiAI Professional",
        subject="Internet plagiati va AI yordamida yozilgan matn indikatori",
    )

    detected_language = ai_assessment.language if ai_assessment else "unknown"
    scan_mode = "QUETEXT REAL API - DEEPSEARCH"
    story: list[object] = [
        Spacer(1, 0.5 * mm),
        Paragraph("Hujjat autentikligi bo‘yicha professional hisobot", styles["title"]),
        Paragraph(
            "Ochiq internet, akademik veb manbalar va AI indikatorlari bo‘yicha "
            "yakuniy tashqi tahlil",
            styles["subtitle"],
        ),
    ]

    metadata = Table(
        [
            [
                Paragraph("HUJJAT", styles["small"]),
                Paragraph(escape(filename), styles["table_bold"]),
            ],
            [
                Paragraph("TEKSHIRUV MA’LUMOTI", styles["small"]),
                Paragraph(
                    checked_at.strftime("%d.%m.%Y • %H:%M")
                    + f"  •  {word_count:,} so‘z  •  "
                    + escape(language_name(detected_language)),
                    styles["table"],
                ),
            ],
            [
                Paragraph("TEKSHIRUV REJIMI", styles["small"]),
                Paragraph(escape(scan_mode), styles["table_bold"]),
            ],
        ],
        colWidths=[38 * mm, 136 * mm],
    )
    metadata.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), PALE_SLATE),
                ("BOX", (0, 0), (-1, -1), 0.6, BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.35, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
            ]
        )
    )
    story.extend([metadata, Spacer(1, 2 * mm)])

    banner_background = PALE_GREEN
    banner_color = GREEN
    banner = Table(
        [
            [
                Paragraph(
                    f"<font color='{banner_color.hexval()}'><b>"
                    f"{escape(conclusion.status_label)}</b></font>"
                    f"<br/><font size='12'><b>{escape(conclusion.headline)}</b></font>",
                    styles["banner_title"],
                )
            ],
            [Paragraph(escape(conclusion.conclusion), styles["banner_body"])],
        ],
        colWidths=[174 * mm],
    )
    banner.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), banner_background),
                ("BOX", (0, 0), (-1, -1), 1, banner_color),
                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                ("TOPPADDING", (0, 0), (-1, 0), 6),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("TOPPADDING", (0, 1), (-1, 1), 1),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 6),
            ]
        )
    )
    story.extend([banner, Spacer(1, 2 * mm)])

    ai_value = (
        "MAVJUD EMAS"
        if not ai_assessment or ai_assessment.score is None
        else f"{ai_assessment.score:.1f}%"
    )
    metrics = Table(
        [
            [
                _metric_card(
                    f"{internet_result.originality:.2f}%",
                    "INTERNET ORIGINALLIGI",
                    styles,
                    PALE_GREEN,
                ),
                _metric_card(
                    f"{internet_result.similarity:.2f}%",
                    "INTERNET O‘XSHASHLIGI",
                    styles,
                    PALE_RED,
                ),
                _metric_card(ai_value, "AI INDIKATORI", styles, PALE_AMBER),
            ]
        ],
        colWidths=[58 * mm] * 3,
    )
    metrics.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 1 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story.extend(
        [
            metrics,
            Paragraph("1. Internet manbalari bo‘yicha natija", styles["heading"]),
            Paragraph(
                f"Quetext DeepSearch tashqi skani yakunlandi. {len(internet_result.sources)} ta "
                f"manba qaytdi. Dalil darajasi: "
                f"<b>{escape(conclusion.evidence_level)}</b>.",
                styles["body"],
            ),
        ]
    )

    if internet_result.sources:
        source_rows: list[list[object]] = [
            [
                Paragraph("№", styles["table_bold"]),
                Paragraph("INTERNET MANBASI", styles["table_bold"]),
                Paragraph("MOS SO‘Z", styles["table_bold"]),
            ]
        ]
        for number, source in enumerate(internet_result.sources[:15], start=1):
            title = escape(source.title)
            if source.url:
                title = (
                    f"<link href={quoteattr(source.url)} color='#2563EB'>{title}</link>"
                    f"<br/><font size='6' color='#64748B'>{escape(source.url[:140])}</font>"
                )
            source_rows.append(
                [
                    Paragraph(str(number), styles["table"]),
                    Paragraph(title, styles["table"]),
                    Paragraph(str(source.matched_words), styles["table_bold"]),
                ]
            )
        source_table = LongTable(
            source_rows,
            colWidths=[9 * mm, 145 * mm, 20 * mm],
            repeatRows=1,
        )
        source_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), PALE_BLUE),
                    ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(source_table)
    else:
        story.append(
            Paragraph(
                "Tekshiruv yakunlandi, lekin hisobotga kiritiladigan internet manbasi topilmadi.",
                styles["body"],
            )
        )

    story.append(Paragraph("2. AI yordamida yozilgan matn indikatori", styles["heading"]))
    if ai_assessment is None:
        story.append(
            Paragraph(
                "AI tahlili ushbu tekshiruvda bajarilmadi. Plagiat natijasi AI tahlili "
                "o‘rnini bosmaydi.",
                styles["body"],
            )
        )
    else:
        ai_score_text = (
            "Foiz mavjud emas" if ai_assessment.score is None else f"{ai_assessment.score:.2f}%"
        )
        ai_table = Table(
            [
                [
                    Paragraph("PROVAYDER", styles["small"]),
                    Paragraph(escape(ai_assessment.provider), styles["table_bold"]),
                ],
                [
                    Paragraph("NATIJA", styles["small"]),
                    Paragraph(escape(ai_score_text), styles["table_bold"]),
                ],
                [
                    Paragraph("ISHONCH", styles["small"]),
                    Paragraph(escape(ai_assessment.confidence), styles["table"]),
                ],
                [
                    Paragraph("TALQIN", styles["small"]),
                    Paragraph(escape(ai_assessment.verdict), styles["table"]),
                ],
            ],
            colWidths=[32 * mm, 142 * mm],
        )
        ai_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, -1), PALE_AMBER),
                    ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(ai_table)
        for reason in ai_assessment.reasons[:6]:
            story.append(Paragraph(f"• {escape(reason)}", styles["body"]))
        story.append(Paragraph(f"<i>{escape(ai_assessment.disclaimer)}</i>", styles["small"]))

    story.append(Paragraph("3. Ekspert tavsiyalari", styles["heading"]))
    for number, recommendation in enumerate(conclusion.recommendations, start=1):
        story.append(Paragraph(f"<b>{number}.</b> {escape(recommendation)}", styles["body"]))

    if authorship_questions:
        story.append(Paragraph("4. Mualliflikni tekshirish savollari", styles["heading"]))
        question_lines = "<br/>".join(
            f"<b>{number}.</b> {escape(question)}"
            for number, question in enumerate(authorship_questions[:3], start=1)
        )
        story.append(
            Paragraph(
                question_lines,
                styles["small"],
            )
        )

    decorate = _page_decorator(regular, bold, report_id)
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
