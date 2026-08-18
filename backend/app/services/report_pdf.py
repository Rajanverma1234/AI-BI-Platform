"""PDF rendering.

ReportLab's Platypus flowables handle pagination, so this module only decides
layout: a cover block, then each section as a heading, its narrative, a metric
strip, its tables and its bullets.

Two details matter for readability. Table cells are Paragraphs rather than raw
strings so long text wraps instead of overflowing the page, and the font size
steps down as a table gets wider, which is what keeps a twelve-column cohort
matrix on one portrait page.
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas.report import ReportData, ReportSection, ReportTable
from app.services.report_builder import cell_text

CONTENT_TYPE = "application/pdf"

_MARGIN = 16 * mm
_PAGE_WIDTH = A4[0] - (2 * _MARGIN)

_ACCENT = colors.HexColor("#1F3864")
_MUTED = colors.HexColor("#5A6472")
_GRID = colors.HexColor("#D5DAE2")
_BAND = colors.HexColor("#F2F4F8")

#: Cell font size by column count - wider tables get smaller type.
_FONT_STEPS = ((5, 8.5), (8, 7.5), (11, 6.5))
_MIN_FONT = 5.5


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=base["Title"], fontSize=20, leading=24, textColor=_ACCENT
        ),
        "subtitle": ParagraphStyle(
            "ReportSubtitle", parent=base["Normal"], fontSize=10.5, leading=15, textColor=_MUTED
        ),
        "heading": ParagraphStyle(
            "SectionHeading",
            parent=base["Heading1"],
            fontSize=14,
            leading=18,
            spaceBefore=6,
            spaceAfter=6,
            textColor=_ACCENT,
        ),
        "subheading": ParagraphStyle(
            "TableHeading", parent=base["Heading2"], fontSize=10.5, leading=14, spaceAfter=3
        ),
        "body": ParagraphStyle(
            "ReportBody", parent=base["BodyText"], fontSize=9.5, leading=14, alignment=TA_LEFT
        ),
        "muted": ParagraphStyle(
            "ReportMuted", parent=base["BodyText"], fontSize=8.5, leading=12, textColor=_MUTED
        ),
        "bullet": ParagraphStyle(
            "ReportBullet",
            parent=base["BodyText"],
            fontSize=9.5,
            leading=13,
            leftIndent=10,
            bulletIndent=2,
            spaceAfter=2,
        ),
    }


def _font_size(column_count: int) -> float:
    for limit, size in _FONT_STEPS:
        if column_count <= limit:
            return size
    return _MIN_FONT


def _escape(text: str) -> str:
    """Platypus reads a subset of HTML, so raw text must be escaped."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _metric_strip(section: ReportSection, styles: dict[str, ParagraphStyle]) -> list[Any]:
    if not section.metrics:
        return []

    label = ParagraphStyle("MetricLabel", parent=styles["muted"], fontSize=7.5, leading=9)
    value = ParagraphStyle(
        "MetricValue", parent=styles["body"], fontSize=12, leading=15, textColor=_ACCENT
    )

    cells = []
    for metric in section.metrics:
        block = [
            Paragraph(_escape(metric.label.upper()), label),
            Paragraph(_escape(metric.value), value),
        ]
        if metric.detail:
            block.append(Paragraph(_escape(metric.detail), label))
        cells.append(block)

    # Four across keeps each tile wide enough for a formatted number.
    rows = [cells[index : index + 4] for index in range(0, len(cells), 4)]
    flowables: list[Any] = []
    for row in rows:
        padded = row + [""] * (4 - len(row))
        table = Table([padded], colWidths=[_PAGE_WIDTH / 4] * 4)
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("BACKGROUND", (0, 0), (-1, -1), _BAND),
                    ("LINEBELOW", (0, 0), (-1, -1), 3, colors.white),
                ]
            )
        )
        flowables.append(table)
    flowables.append(Spacer(1, 6))
    return flowables


def _table(table: ReportTable, styles: dict[str, ParagraphStyle]) -> list[Any]:
    if not table.columns:
        return []

    size = _font_size(len(table.columns))
    header_style = ParagraphStyle(
        "CellHeader",
        parent=styles["body"],
        fontSize=size,
        leading=size + 2,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )
    cell_style = ParagraphStyle(
        "Cell", parent=styles["body"], fontSize=size, leading=size + 2.5
    )

    grid: list[list[Any]] = [
        [Paragraph(_escape(str(column)), header_style) for column in table.columns]
    ]
    for row in table.rows:
        # Pad or trim so a malformed row can never break the layout.
        values = list(row)[: len(table.columns)]
        values += [None] * (len(table.columns) - len(values))
        grid.append([Paragraph(_escape(cell_text(value)), cell_style) for value in values])

    # The first column holds labels and gets a double share of the width.
    weights = [2.0] + [1.0] * (len(table.columns) - 1)
    total = sum(weights)
    widths = [(_PAGE_WIDTH * weight) / total for weight in weights]

    flowable = Table(grid, colWidths=widths, repeatRows=1)
    flowable.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _ACCENT),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, _BAND]),
                ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )

    flowables: list[Any] = []
    if table.title:
        flowables.append(Paragraph(_escape(table.title), styles["subheading"]))
    flowables.append(flowable)
    if table.note:
        flowables.append(Spacer(1, 3))
        flowables.append(Paragraph(_escape(table.note), styles["muted"]))
    flowables.append(Spacer(1, 10))
    return flowables


def _section(section: ReportSection, styles: dict[str, ParagraphStyle]) -> list[Any]:
    flowables: list[Any] = [Paragraph(_escape(section.title), styles["heading"])]

    if section.unavailable_reason:
        flowables.append(Paragraph(_escape(section.unavailable_reason), styles["muted"]))
        flowables.append(Spacer(1, 8))

    for paragraph in section.narrative:
        flowables.append(Paragraph(_escape(paragraph), styles["body"]))
        flowables.append(Spacer(1, 4))

    flowables.extend(_metric_strip(section, styles))

    for table in section.tables:
        flowables.extend(_table(table, styles))

    for bullet in section.bullets:
        flowables.append(Paragraph(_escape(bullet), styles["bullet"], bulletText="•"))

    flowables.append(Spacer(1, 12))
    return flowables


def _cover(data: ReportData, styles: dict[str, ParagraphStyle]) -> list[Any]:
    flowables: list[Any] = [
        Spacer(1, 40),
        Paragraph(_escape(data.title), styles["title"]),
        Spacer(1, 8),
    ]
    if data.subtitle:
        flowables.append(Paragraph(_escape(data.subtitle), styles["subtitle"]))
    flowables.append(Spacer(1, 20))

    facts = [
        ("Dataset", data.dataset_name),
        ("Source", data.version_label),
        ("Rows", f"{data.row_count:,}"),
        ("Columns", f"{data.column_count:,}"),
        ("Generated", data.generated_at.strftime("%Y-%m-%d %H:%M UTC")),
        ("Generated by", data.generated_by),
        (
            "AI narrative",
            "Included" if data.ai_available else (data.ai_status or "Not included"),
        ),
    ]
    table = Table(
        [
            [Paragraph(_escape(label), styles["muted"]), Paragraph(_escape(value), styles["body"])]
            for label, value in facts
        ],
        colWidths=[_PAGE_WIDTH * 0.3, _PAGE_WIDTH * 0.7],
    )
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -2), 0.4, _GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (0, -1), 0),
            ]
        )
    )
    flowables.append(table)

    flowables.append(Spacer(1, 18))
    flowables.append(Paragraph("Contents", styles["subheading"]))
    for index, section in enumerate(data.sections, start=1):
        flowables.append(
            Paragraph(f"{index}. {_escape(section.title)}", styles["body"])
        )

    flowables.append(PageBreak())
    return flowables


def _skipped(data: ReportData, styles: dict[str, ParagraphStyle]) -> list[Any]:
    if not data.skipped:
        return []
    flowables: list[Any] = [
        Paragraph("Sections not included", styles["heading"]),
        Paragraph(
            "These were requested or offered by the template but this dataset "
            "does not support them.",
            styles["body"],
        ),
        Spacer(1, 6),
    ]
    flowables.extend(
        _table(
            ReportTable(
                columns=["Section", "Reason"],
                rows=[[item["section"], item["reason"]] for item in data.skipped],
            ),
            styles,
        )
    )
    return flowables


def _decorate(canvas: Any, document: Any) -> None:
    """Footer with the page number, drawn on every page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(_MUTED)
    canvas.drawRightString(A4[0] - _MARGIN, 10 * mm, f"Page {document.page}")
    canvas.restoreState()


def render(data: ReportData) -> bytes:
    """Render the report as a paginated PDF."""
    styles = _styles()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=_MARGIN,
        rightMargin=_MARGIN,
        topMargin=_MARGIN,
        bottomMargin=_MARGIN,
        title=data.title,
        author=data.generated_by,
        subject=f"{data.dataset_name} - {data.template.value}",
    )

    story: list[Any] = _cover(data, styles)
    for section in data.sections:
        # Keep a heading with at least its opening prose.
        story.extend(_section(section, styles))
    story.extend(_skipped(data, styles))

    if len(story) <= 1:
        story.append(
            KeepTogether(Paragraph("This report has no sections to show.", styles["body"]))
        )

    document.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buffer.getvalue()
