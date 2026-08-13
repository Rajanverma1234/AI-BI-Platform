"""Profiling and data-quality schemas."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class DetectedType(enum.StrEnum):
    """Normalised column type vocabulary used across profiling and cleaning."""

    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATETIME = "datetime"
    STRING = "string"
    #: Every value is null, so no type can be inferred.
    EMPTY = "empty"


class NumericStats(BaseModel):
    """Populated only for numeric columns. All fields are null-safe."""

    minimum: float | None = None
    maximum: float | None = None
    mean: float | None = None
    median: float | None = None
    std_dev: float | None = None
    sum: float | None = None
    percentile_25: float | None = None
    percentile_50: float | None = None
    percentile_75: float | None = None


class ValueCount(BaseModel):
    value: str
    count: int
    percentage: float


class CategoricalStats(BaseModel):
    """Populated for string/boolean columns. `top_values` is always bounded."""

    unique_count: int
    most_frequent_value: str | None = None
    most_frequent_count: int | None = None
    most_frequent_percentage: float | None = None
    top_values: list[ValueCount] = Field(default_factory=list)


class DateTimeStats(BaseModel):
    minimum: datetime | None = None
    maximum: datetime | None = None
    unique_count: int = 0
    missing_count: int = 0


class ColumnProfile(BaseModel):
    column_name: str
    detected_data_type: DetectedType
    null_count: int
    null_percentage: float
    non_null_count: int
    unique_count: int
    unique_percentage: float
    numeric: NumericStats | None = None
    categorical: CategoricalStats | None = None
    datetime_stats: DateTimeStats | None = None


class DatasetProfile(BaseModel):
    dataset_id: uuid.UUID
    #: Null when profiling the original upload; set when profiling a version.
    version_id: uuid.UUID | None = None
    row_count: int
    column_count: int
    duplicate_row_count: int
    duplicate_row_percentage: float
    missing_cell_count: int
    missing_cell_percentage: float
    columns: list[ColumnProfile] = Field(default_factory=list)


# --- Data quality ------------------------------------------------------------


class QualitySeverity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class QualityStatus(enum.StrEnum):
    GOOD = "good"
    WARNING = "warning"
    CRITICAL = "critical"


class QualityIssueType(enum.StrEnum):
    MISSING_VALUES = "missing_values"
    DUPLICATE_ROWS = "duplicate_rows"
    EMPTY_COLUMN = "empty_column"
    HIGH_MISSING = "high_missing"
    CONSTANT_COLUMN = "constant_column"
    MIXED_TYPES = "mixed_types"
    SUSPICIOUS_VALUES = "suspicious_values"
    POSSIBLE_WRONG_TYPE = "possible_wrong_type"


class DataQualityIssue(BaseModel):
    issue_type: QualityIssueType
    severity: QualitySeverity
    #: Null for dataset-wide issues such as duplicate rows.
    column: str | None = None
    message: str
    affected_rows: int = 0
    affected_percentage: float = 0.0
    #: Cleaning operations that would address this issue.
    suggested_operations: list[str] = Field(default_factory=list)


class DataQualitySummary(BaseModel):
    dataset_id: uuid.UUID
    version_id: uuid.UUID | None = None
    status: QualityStatus
    #: 0-100; 100 means no issues were detected.
    score: int = Field(ge=0, le=100)
    total_issues: int
    critical_count: int
    warning_count: int
    info_count: int
    issues: list[DataQualityIssue] = Field(default_factory=list)
    #: Human-readable description of the thresholds that produced `status`.
    rules: list[str] = Field(default_factory=list)
