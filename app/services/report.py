import base64
import hashlib
import os
from datetime import UTC, datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
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
from app.services.internal_similarity import MultiSourceResult
from app.services.quetext import InternetScanResult

NAVY = colors.HexColor("#123B5D")
TURQUOISE = colors.HexColor("#1F8E8A")
GOLD = colors.HexColor("#B88A3B")
GREEN = colors.HexColor("#2E6D54")
RED = colors.HexColor("#9A4E43")
AMBER = colors.HexColor("#9A6A27")
SLATE = colors.HexColor("#384A55")
MUTED = colors.HexColor("#6C7A80")
BORDER = colors.HexColor("#D8D2C4")
PAPER = colors.HexColor("#FFFEF8")
PALE_TURQUOISE = colors.HexColor("#F0F8F6")
PALE_GOLD = colors.HexColor("#FBF7EC")
PALE_RED = colors.HexColor("#FCF4F2")
MAX_TABLE_FRAGMENT_CHARS = 900


@lru_cache(maxsize=1)
def _brand_logo_bytes() -> bytes | None:
    """Load the official PLAG AI UZ logo; the report remains usable if the asset is absent."""
    override = os.getenv("PLAGIAI_LOGO_FILE", "").strip()
    if override:
        path = Path(override)
        if path.is_file():
            return path.read_bytes()

    encoded_path = Path(__file__).resolve().parents[1] / "assets" / "plagai_logo.png.b64"
    if not encoded_path.is_file():
        return None
    try:
        encoded = encoded_path.read_text(encoding="ascii").strip()
        return base64.b64decode(encoded, validate=True)
    except (OSError, ValueError):
        return None


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
    for path in display_paths:
        if path.exists():
            if "PlagiAI-Display" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("PlagiAI-Display", str(path)))
            display = "PlagiAI-Display"
            break
    return regular, bold, display


def _styles(regular: str, bold: str, display: str) -> dict[str, ParagraphStyle]:
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
            fontName=display,
            fontSize=16.8,
            leading=20,
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
            fontSize=10.5,
            leading=13.2,
            textColor=NAVY,
            spaceBefore=1.2 * mm,
            spaceAfter=1.0 * mm,
            keepWithNext=True,
        ),
        "metric_value": ParagraphStyle(
            "MetricValue",
            parent=base["BodyText"],
            fontName=display,
            fontSize=14.5,
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
    width: float = 56 * mm,
) -> Table:
    card = Table(
        [
            [Paragraph(escape(value), styles["metric_value"])],
            [Paragraph(escape(label), styles["metric_label"])],
        ],
        colWidths=[width],
        rowHeights=[9 * mm, 6.5 * mm],
    )
    card.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("LINEABOVE", (0, 0), (-1, 0), 0.7, GOLD),
                ("LINEBELOW", (0, -1), (-1, -1), 0.7, NAVY),
                ("LINEBEFORE", (0, 0), (0, -1), 0.35, BORDER),
                ("LINEAFTER", (-1, 0), (-1, -1), 0.35, BORDER),
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


def _split_table_fragment(text: str, limit: int = MAX_TABLE_FRAGMENT_CHARS) -> list[str]:
    """Split evidence into rows that ReportLab can paginate without losing content."""
    value = text.strip()
    if not value:
        return ["-"]

    chunks: list[str] = []
    while len(value) > limit:
        split_at = value.rfind(" ", 0, limit + 1)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(value[:split_at])
        value = value[split_at:]
        if value.startswith(" "):
            value = value[1:]
    if value:
        chunks.append(value)
    return chunks


def _draw_step_motif(canvas, x: float, y: float, size: float) -> None:
    """Minimal stepped textile motif with no star-shaped geometry."""
    canvas.saveState()
    canvas.translate(x, y)
    canvas.setStrokeColor(TURQUOISE)
    canvas.setLineWidth(0.35)
    upper = canvas.beginPath()
    upper.moveTo(-size, 0)
    upper.lineTo(-size * 0.5, size * 0.34)
    upper.lineTo(0, 0)
    upper.lineTo(size * 0.5, size * 0.34)
    upper.lineTo(size, 0)
    canvas.drawPath(upper, stroke=1, fill=0)
    canvas.setStrokeColor(GOLD)
    canvas.setLineWidth(0.28)
    lower = canvas.beginPath()
    lower.moveTo(-size * 0.72, -size * 0.27)
    lower.lineTo(-size * 0.34, -size * 0.04)
    lower.lineTo(0, -size * 0.27)
    lower.lineTo(size * 0.34, -size * 0.04)
    lower.lineTo(size * 0.72, -size * 0.27)
    canvas.drawPath(lower, stroke=1, fill=0)
    canvas.restoreState()


def _page_decorator(regular: str, bold: str, report_id: str):
    def draw(canvas, document) -> None:
        canvas.saveState()
        width, height = A4
        canvas.setFillColor(PAPER)
        canvas.rect(0, 0, width, height, stroke=0, fill=1)
        canvas.setStrokeColor(GOLD)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, height - 21 * mm, width - 18 * mm, height - 21 * mm)
        _draw_step_motif(canvas, 20.5 * mm, height - 21 * mm, 2.5 * mm)
        _draw_step_motif(canvas, width - 20.5 * mm, height - 21 * mm, 2.5 * mm)
        logo = _brand_logo_bytes()
        if logo:
            canvas.drawImage(
                ImageReader(BytesIO(logo)),
                14 * mm,
                height - 19 * mm,
                width=38 * mm,
                height=19.8 * mm,
                preserveAspectRatio=True,
                anchor="c",
                mask="auto",
            )
        else:
            canvas.setFont(bold, 8)
            canvas.setFillColor(NAVY)
            canvas.drawString(18 * mm, height - 11 * mm, "PLAG AI UZ  •  AKADEMIK HALOLLIK")
        canvas.setFont(regular, 7)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(width - 18 * mm, height - 11 * mm, f"Hisobot № {report_id}")
        canvas.setStrokeColor(GOLD)
        canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
        canvas.drawString(18 * mm, 9 * mm, "Elektron hujjat  •  Akademik ekspertiza uchun")
        canvas.drawRightString(
            width - 18 * mm,
            9 * mm,
            f"V6 MULTI-SOURCE  |  {document.page}-sahifa",
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
    multi_source_result: MultiSourceResult | None = None,
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

    checked_at = checked_at or datetime.now(UTC)
    if multi_source_result is None:
        multi_source_result = MultiSourceResult(
            internet_similarity=float(internet_result.similarity),
            internal_similarity=0.0,
            combined_similarity=float(internet_result.similarity),
            combined_originality=float(internet_result.originality),
            internet_matched_words=round(word_count * float(internet_result.similarity) / 100.0),
            internal_matched_words=0,
            deduplicated_matched_words=round(
                word_count * float(internet_result.similarity) / 100.0
            ),
            total_words=word_count,
            internal_sources=[],
        )
    regular, bold, display = _fonts()
    styles = _styles(regular, bold, display)
    conclusion = build_professional_conclusion(
        internet_result,
        ai_assessment,
        overall_similarity=multi_source_result.combined_similarity,
        internal_similarity=multi_source_result.internal_similarity,
    )
    report_id = _report_id(filename, checked_at)
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=25 * mm,
        bottomMargin=16 * mm,
        title=f"PlagiAI professional hisoboti — {filename}",
        author="PlagiAI Professional",
        subject="Internet, akademik va PlagAI ichki bazasi bo‘yicha o‘xshashlik hisoboti",
    )

    detected_language = ai_assessment.language if ai_assessment else "unknown"
    scan_mode = "QUETEXT DEEPSEARCH + PLAGAI INTERNAL DATABASE"
    story: list[object] = [
        Spacer(1, 0.8 * mm),
        Paragraph("TO‘LIQ TEKSHIRUV HISOBOTI", styles["title"]),
        Paragraph(
            "Internet, akademik manbalar va PlagAI ichki hujjatlar bazasi bilan "
            "o‘xshashlik, mos fragmentlar va AI indikatori bo‘yicha elektron qayd",
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
                ("BACKGROUND", (0, 0), (0, -1), PALE_GOLD),
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

    banner_background = PALE_TURQUOISE
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
                ("LINEBEFORE", (0, 0), (0, -1), 2.2, banner_color),
                ("LINEABOVE", (0, 0), (-1, 0), 0.45, BORDER),
                ("LINEBELOW", (0, -1), (-1, -1), 0.45, BORDER),
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
    card_width = 41.5 * mm
    metrics = Table(
        [
            [
                _metric_card(
                    f"{multi_source_result.combined_originality:.2f}%",
                    "UMUMIY ORIGINALLIK",
                    styles,
                    PAPER,
                    card_width,
                ),
                _metric_card(
                    f"{multi_source_result.combined_similarity:.2f}%",
                    "UMUMIY O‘XSHASHLIK",
                    styles,
                    PAPER,
                    card_width,
                ),
                _metric_card(
                    f"{multi_source_result.internet_similarity:.2f}%",
                    "INTERNET / AKADEMIK",
                    styles,
                    PAPER,
                    card_width,
                ),
                _metric_card(
                    f"{multi_source_result.internal_similarity:.2f}%",
                    "PLAGAI ICHKI BAZA",
                    styles,
                    PAPER,
                    card_width,
                ),
            ]
        ],
        colWidths=[43.5 * mm] * 4,
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
            Paragraph(
                f"AI indikatori: <b>{escape(ai_value)}</b>  •  "
                f"Takrorlanmaydigan mos so‘zlar: "
                f"<b>{multi_source_result.deduplicated_matched_words:,}</b>",
                styles["small"],
            ),
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
                Paragraph("MOSLIK", styles["table_bold"]),
                Paragraph("MOS FRAGMENT", styles["table_bold"]),
            ]
        ]
        for number, source in enumerate(internet_result.sources, start=1):
            title = escape(source.title)
            if source.url:
                title = (
                    f"<link href={quoteattr(source.url)} color='#2563EB'>{title}</link>"
                    f"<br/><font size='6' color='#64748B'>{escape(source.url[:140])}</font>"
                )
            similarity_text = f"{source.matched_words} so‘z"
            if source.similarity is not None:
                similarity_text += f"<br/><b>{source.similarity:.2f}%</b>"
            snippet_chunks = _split_table_fragment(source.introduction or "")
            for chunk_number, snippet in enumerate(snippet_chunks, start=1):
                first_chunk = chunk_number == 1
                source_cell = (
                    title
                    if first_chunk
                    else f"(davomi {chunk_number}/{len(snippet_chunks)})"
                )
                source_rows.append(
                    [
                        Paragraph(str(number) if first_chunk else "", styles["table"]),
                        Paragraph(source_cell, styles["table"]),
                        Paragraph(similarity_text if first_chunk else "", styles["table"]),
                        Paragraph(escape(snippet), styles["table"]),
                    ]
                )
        source_table = LongTable(
            source_rows,
            colWidths=[8 * mm, 69 * mm, 23 * mm, 74 * mm],
            repeatRows=1,
        )
        source_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), PALE_TURQUOISE),
                    ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
                    ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        for row in range(2, len(source_rows), 2):
            source_table.setStyle(TableStyle([("BACKGROUND", (0, row), (-1, row), PALE_GOLD)]))
        story.append(source_table)
    else:
        story.append(
            Paragraph(
                "Tekshiruv yakunlandi, lekin hisobotga kiritiladigan internet manbasi topilmadi.",
                styles["body"],
            )
        )

    story.append(Paragraph("2. PlagAI ichki hujjatlar bazasi", styles["heading"]))
    if multi_source_result.internal_sources:
        internal_rows: list[list[object]] = [
            [
                Paragraph("№", styles["table_bold"]),
                Paragraph("ICHKI MANBA", styles["table_bold"]),
                Paragraph("MOSLIK", styles["table_bold"]),
                Paragraph("MOS FRAGMENT", styles["table_bold"]),
            ]
        ]
        row_number = 1
        for source in multi_source_result.internal_sources:
            for match in source.matches:
                match_chunks = _split_table_fragment(match.text)
                for chunk_number, snippet in enumerate(match_chunks, start=1):
                    first_chunk = chunk_number == 1
                    source_label = (
                        escape(source.label)
                        if first_chunk
                        else f"(davomi {chunk_number}/{len(match_chunks)})"
                    )
                    internal_rows.append(
                        [
                            Paragraph(str(row_number) if first_chunk else "", styles["table"]),
                            Paragraph(source_label, styles["table_bold"]),
                            Paragraph(
                                (
                                    f"{match.matched_words} so‘z<br/>"
                                    f"<b>{source.similarity:.2f}%</b>"
                                    if first_chunk
                                    else ""
                                ),
                                styles["table"],
                            ),
                            Paragraph(escape(snippet), styles["table"]),
                        ]
                    )
                row_number += 1
        internal_table = LongTable(
            internal_rows,
            colWidths=[8 * mm, 54 * mm, 25 * mm, 87 * mm],
            repeatRows=1,
        )
        internal_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), PALE_GOLD),
                    ("TEXTCOLOR", (0, 0), (-1, 0), NAVY),
                    ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(internal_table)
    else:
        story.append(
            Paragraph(
                "Oldingi PlagAI hujjatlarida kamida 8 so‘zli ishonchli mos fragment topilmadi.",
                styles["body"],
            )
        )

    story.append(Paragraph("3. AI yordamida yozilgan matn indikatori", styles["heading"]))
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
                    ("BACKGROUND", (0, 0), (0, -1), PALE_GOLD),
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

    story.append(Paragraph("4. Ekspert tavsiyalari", styles["heading"]))
    for number, recommendation in enumerate(conclusion.recommendations, start=1):
        story.append(Paragraph(f"<b>{number}.</b> {escape(recommendation)}", styles["body"]))

    if authorship_questions:
        story.append(Paragraph("5. Mualliflikni tekshirish savollari", styles["heading"]))
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
