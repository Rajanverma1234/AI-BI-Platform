"""Deterministic data-quality detection.

Every rule below is a fixed threshold applied to the computed profile. No
model, no heuristic scoring, no LLM - the same dataset always yields the same
issues, severities and status.

Thresholds live in RULES so they can be shown to the user alongside the result.
"""

from __future__ import annotations

import uuid

import pandas as pd

from app.schemas.profiling import (
    ColumnProfile,
    DataQualityIssue,
    DataQualitySummary,
    DatasetProfile,
    DetectedType,
    QualityIssueType,
    QualitySeverity,
    QualityStatus,
)

# --- Thresholds --------------------------------------------------------------

#: A column missing at least this share of values is critical.
HIGH_MISSING_CRITICAL_PCT = 50.0
#: Above this, missing values are a warning.
MISSING_WARNING_PCT = 5.0
#: Duplicate rows at or above this share of the dataset are critical.
DUPLICATE_CRITICAL_PCT = 10.0
#: A string column whose values are at least this convertible to numbers is
#: probably the wrong type.
WRONG_TYPE_PCT = 90.0
#: A string column with at least this share of non-numeric values mixed in with
#: numeric ones is flagged as mixed-type.
MIXED_TYPE_MIN_PCT = 10.0
#: Values treated as placeholders for "no data".
SUSPICIOUS_VALUES = frozenset(
    {"n/a", "na", "null", "none", "nil", "-", "--", "?", "unknown", "#n/a", "nan", ""}
)
#: Score deductions per issue severity.
SCORE_PENALTY = {
    QualitySeverity.CRITICAL: 20,
    QualitySeverity.WARNING: 8,
    QualitySeverity.INFO: 2,
}

RULES: list[str] = [
    f"Column missing >= {HIGH_MISSING_CRITICAL_PCT:.0f}% of values -> critical",
    f"Column missing > {MISSING_WARNING_PCT:.0f}% of values -> warning",
    "Column with no values at all -> critical (empty column)",
    "Column with a single repeated value -> warning (constant column)",
    f"Duplicate rows >= {DUPLICATE_CRITICAL_PCT:.0f}% of rows -> critical, otherwise warning",
    f"Text column where >= {WRONG_TYPE_PCT:.0f}% of values parse as numbers -> warning "
    "(possible wrong type)",
    f"Text column mixing numeric and non-numeric values (each >= {MIXED_TYPE_MIN_PCT:.0f}%) "
    "-> warning (mixed types)",
    "Placeholder values such as 'N/A', 'null' or '-' present -> warning (suspicious values)",
    "Status is critical if any critical issue exists, warning if any warning exists, "
    "otherwise good",
]


def _pct(part: int, whole: int) -> float:
    return round((part / whole) * 100, 2) if whole else 0.0


def _missing_issues(column: ColumnProfile) -> list[DataQualityIssue]:
    if column.null_count == 0:
        return []

    if column.non_null_count == 0:
        return [
            DataQualityIssue(
                issue_type=QualityIssueType.EMPTY_COLUMN,
                severity=QualitySeverity.CRITICAL,
                column=column.column_name,
                message=f"Column '{column.column_name}' contains no values at all.",
                affected_rows=column.null_count,
                affected_percentage=column.null_percentage,
                suggested_operations=["drop_column"],
            )
        ]

    if column.null_percentage >= HIGH_MISSING_CRITICAL_PCT:
        return [
            DataQualityIssue(
                issue_type=QualityIssueType.HIGH_MISSING,
                severity=QualitySeverity.CRITICAL,
                column=column.column_name,
                message=(
                    f"Column '{column.column_name}' is missing "
                    f"{column.null_percentage:.1f}% of its values."
                ),
                affected_rows=column.null_count,
                affected_percentage=column.null_percentage,
                suggested_operations=["fill_missing", "drop_column", "drop_missing_rows"],
            )
        ]

    severity = (
        QualitySeverity.WARNING
        if column.null_percentage > MISSING_WARNING_PCT
        else QualitySeverity.INFO
    )
    return [
        DataQualityIssue(
            issue_type=QualityIssueType.MISSING_VALUES,
            severity=severity,
            column=column.column_name,
            message=(
                f"Column '{column.column_name}' has {column.null_count} missing "
                f"value(s) ({column.null_percentage:.1f}%)."
            ),
            affected_rows=column.null_count,
            affected_percentage=column.null_percentage,
            suggested_operations=["fill_missing", "drop_missing_rows"],
        )
    ]


def _constant_issue(column: ColumnProfile) -> DataQualityIssue | None:
    if column.non_null_count == 0 or column.unique_count != 1:
        return None
    return DataQualityIssue(
        issue_type=QualityIssueType.CONSTANT_COLUMN,
        severity=QualitySeverity.WARNING,
        column=column.column_name,
        message=(
            f"Column '{column.column_name}' has the same value in every row, "
            "so it carries no information."
        ),
        affected_rows=column.non_null_count,
        affected_percentage=100.0,
        suggested_operations=["drop_column"],
    )


def _text_column_issues(
    column: ColumnProfile, series: pd.Series
) -> list[DataQualityIssue]:
    """Numeric-looking text, mixed types and placeholder values."""
    issues: list[DataQualityIssue] = []
    non_null = series.dropna()
    if non_null.empty:
        return issues

    as_text = non_null.astype(str).str.strip()
    total = len(as_text)

    numeric_mask = pd.to_numeric(as_text, errors="coerce").notna()
    numeric_pct = _pct(int(numeric_mask.sum()), total)
    non_numeric_pct = round(100.0 - numeric_pct, 2)

    if numeric_pct >= WRONG_TYPE_PCT:
        issues.append(
            DataQualityIssue(
                issue_type=QualityIssueType.POSSIBLE_WRONG_TYPE,
                severity=QualitySeverity.WARNING,
                column=column.column_name,
                message=(
                    f"Column '{column.column_name}' is stored as text but "
                    f"{numeric_pct:.1f}% of its values are numbers."
                ),
                affected_rows=int(numeric_mask.sum()),
                affected_percentage=numeric_pct,
                suggested_operations=["convert_type"],
            )
        )
    elif numeric_pct >= MIXED_TYPE_MIN_PCT and non_numeric_pct >= MIXED_TYPE_MIN_PCT:
        issues.append(
            DataQualityIssue(
                issue_type=QualityIssueType.MIXED_TYPES,
                severity=QualitySeverity.WARNING,
                column=column.column_name,
                message=(
                    f"Column '{column.column_name}' mixes numeric "
                    f"({numeric_pct:.1f}%) and text ({non_numeric_pct:.1f}%) values."
                ),
                affected_rows=int(numeric_mask.sum()),
                affected_percentage=numeric_pct,
                suggested_operations=["convert_type", "fill_missing"],
            )
        )

    suspicious_mask = as_text.str.lower().isin(SUSPICIOUS_VALUES)
    suspicious_count = int(suspicious_mask.sum())
    if suspicious_count:
        issues.append(
            DataQualityIssue(
                issue_type=QualityIssueType.SUSPICIOUS_VALUES,
                severity=QualitySeverity.WARNING,
                column=column.column_name,
                message=(
                    f"Column '{column.column_name}' contains {suspicious_count} "
                    "placeholder value(s) such as 'N/A' or '-' that are not real data."
                ),
                affected_rows=suspicious_count,
                affected_percentage=_pct(suspicious_count, total),
                suggested_operations=["fill_missing"],
            )
        )

    return issues


def _duplicate_issue(profile: DatasetProfile) -> DataQualityIssue | None:
    if profile.duplicate_row_count == 0:
        return None
    severity = (
        QualitySeverity.CRITICAL
        if profile.duplicate_row_percentage >= DUPLICATE_CRITICAL_PCT
        else QualitySeverity.WARNING
    )
    return DataQualityIssue(
        issue_type=QualityIssueType.DUPLICATE_ROWS,
        severity=severity,
        column=None,
        message=(
            f"{profile.duplicate_row_count} duplicate row(s) "
            f"({profile.duplicate_row_percentage:.1f}% of the dataset)."
        ),
        affected_rows=profile.duplicate_row_count,
        affected_percentage=profile.duplicate_row_percentage,
        suggested_operations=["remove_duplicates"],
    )


def assess_quality(
    profile: DatasetProfile,
    frame: pd.DataFrame,
    *,
    dataset_id: uuid.UUID,
    version_id: uuid.UUID | None = None,
) -> DataQualitySummary:
    """Apply every rule and produce the deterministic quality summary."""
    issues: list[DataQualityIssue] = []

    duplicate = _duplicate_issue(profile)
    if duplicate:
        issues.append(duplicate)

    for column in profile.columns:
        issues.extend(_missing_issues(column))

        constant = _constant_issue(column)
        if constant:
            issues.append(constant)

        if column.detected_data_type is DetectedType.STRING:
            issues.extend(_text_column_issues(column, frame[column.column_name]))

    critical = sum(1 for issue in issues if issue.severity is QualitySeverity.CRITICAL)
    warning = sum(1 for issue in issues if issue.severity is QualitySeverity.WARNING)
    info = sum(1 for issue in issues if issue.severity is QualitySeverity.INFO)

    if critical:
        status = QualityStatus.CRITICAL
    elif warning:
        status = QualityStatus.WARNING
    else:
        status = QualityStatus.GOOD

    penalty = sum(SCORE_PENALTY[issue.severity] for issue in issues)
    score = max(0, min(100, 100 - penalty))

    # Severity first, then column, so the order is stable across runs.
    severity_rank = {
        QualitySeverity.CRITICAL: 0,
        QualitySeverity.WARNING: 1,
        QualitySeverity.INFO: 2,
    }
    issues.sort(key=lambda issue: (severity_rank[issue.severity], issue.column or ""))

    return DataQualitySummary(
        dataset_id=dataset_id,
        version_id=version_id,
        status=status,
        score=score,
        total_issues=len(issues),
        critical_count=critical,
        warning_count=warning,
        info_count=info,
        issues=issues,
        rules=RULES,
    )
