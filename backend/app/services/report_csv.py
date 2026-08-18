"""CSV rendering.

A report is a document, not a rectangle, so a single CSV cannot be a faithful
copy of it. This writes a labelled flat file instead: each section is preceded
by a ``## <title>`` marker, and metrics, tables and bullets are written as
labelled rows. That keeps the whole report greppable and loadable into a
spreadsheet without pretending it is one clean table.

Encoded UTF-8 with a BOM so Excel opens non-ASCII text correctly.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from app.schemas.report import ReportData, ReportSection
from app.services.report_builder import cell_text

CONTENT_TYPE = "text/csv; charset=utf-8"


def _write_section(writer: Any, section: ReportSection) -> None:
    writer.writerow([])
    writer.writerow([f"## {section.title}"])

    if section.unavailable_reason:
        writer.writerow(["Not available", section.unavailable_reason])

    for paragraph in section.narrative:
        writer.writerow(["Narrative", paragraph])

    if section.metrics:
        writer.writerow([])
        writer.writerow(["Metric", "Value", "Detail"])
        for metric in section.metrics:
            writer.writerow([metric.label, metric.value, metric.detail or ""])

    for table in section.tables:
        writer.writerow([])
        if table.title:
            writer.writerow([f"# {table.title}"])
        writer.writerow(table.columns)
        for row in table.rows:
            writer.writerow([cell_text(value) for value in row])
        if table.note:
            writer.writerow([table.note])

    if section.bullets:
        writer.writerow([])
        for bullet in section.bullets:
            writer.writerow(["-", bullet])


def render(data: ReportData) -> bytes:
    """Render the report as a labelled CSV document."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")

    writer.writerow([data.title])
    if data.subtitle:
        writer.writerow([data.subtitle])
    writer.writerow(["Dataset", data.dataset_name])
    writer.writerow(["Source", data.version_label])
    writer.writerow(["Rows", data.row_count, "Columns", data.column_count])
    writer.writerow(["Generated", data.generated_at.isoformat(), "by", data.generated_by])
    if data.ai_status:
        writer.writerow(["AI narrative", "included" if data.ai_available else data.ai_status])

    for section in data.sections:
        _write_section(writer, section)

    if data.skipped:
        writer.writerow([])
        writer.writerow(["## Sections not included"])
        writer.writerow(["Section", "Reason"])
        for item in data.skipped:
            writer.writerow([item["section"], item["reason"]])

    # utf-8-sig: Excel needs the BOM to detect UTF-8 in a .csv.
    return buffer.getvalue().encode("utf-8-sig")
