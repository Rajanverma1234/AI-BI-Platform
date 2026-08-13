"""Cleaning pipeline schemas.

Operations are a discriminated union on ``operation``, so each kind carries
exactly the parameters it needs and FastAPI rejects malformed pipelines before
any service code runs. The list is ordered and executed in order, which is what
makes a pipeline reproducible.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.common import Page
from app.schemas.profiling import DetectedType


class MissingStrategy(enum.StrEnum):
    MEAN = "mean"
    MEDIAN = "median"
    MODE = "mode"
    FORWARD_FILL = "forward_fill"
    BACKWARD_FILL = "backward_fill"
    CUSTOM = "custom"


class OutlierMethod(enum.StrEnum):
    IQR = "iqr"
    ZSCORE = "zscore"


class OutlierAction(enum.StrEnum):
    REMOVE = "remove"
    CAP = "cap"


class ConvertibleType(enum.StrEnum):
    """Target types a column may be converted to."""

    STRING = "string"
    INTEGER = "integer"
    FLOAT = "float"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"


# --- Operations --------------------------------------------------------------


class FillMissingOperation(BaseModel):
    operation: Literal["fill_missing"] = "fill_missing"
    column: str
    strategy: MissingStrategy
    #: Required when strategy is "custom"; ignored otherwise.
    value: str | float | bool | None = None


class DropMissingRowsOperation(BaseModel):
    operation: Literal["drop_missing_rows"] = "drop_missing_rows"
    #: Null drops rows with a null in any column.
    column: str | None = None


class RemoveDuplicatesOperation(BaseModel):
    operation: Literal["remove_duplicates"] = "remove_duplicates"
    #: Null compares whole rows; otherwise only these columns.
    subset: list[str] | None = None


class ConvertTypeOperation(BaseModel):
    operation: Literal["convert_type"] = "convert_type"
    column: str
    to_type: ConvertibleType
    #: When true, unconvertible values become null instead of failing the run.
    errors_to_null: bool = False


class RenameColumnOperation(BaseModel):
    operation: Literal["rename_column"] = "rename_column"
    column: str
    new_name: str = Field(min_length=1, max_length=255)


class DropColumnOperation(BaseModel):
    operation: Literal["drop_column"] = "drop_column"
    column: str


class ReorderColumnsOperation(BaseModel):
    operation: Literal["reorder_columns"] = "reorder_columns"
    #: Columns in the desired order; any omitted columns keep their order after.
    order: list[str] = Field(min_length=1)


class HandleOutliersOperation(BaseModel):
    operation: Literal["handle_outliers"] = "handle_outliers"
    column: str
    method: OutlierMethod = OutlierMethod.IQR
    action: OutlierAction = OutlierAction.REMOVE
    #: IQR multiplier, or the z-score cutoff, depending on `method`.
    threshold: float = Field(default=1.5, gt=0, le=10)


CleaningOperation = Annotated[
    FillMissingOperation
    | DropMissingRowsOperation
    | RemoveDuplicatesOperation
    | ConvertTypeOperation
    | RenameColumnOperation
    | DropColumnOperation
    | ReorderColumnsOperation
    | HandleOutliersOperation,
    Field(discriminator="operation"),
]

#: Guards against a pipeline large enough to be a denial-of-service vector.
MAX_OPERATIONS = 100


# --- Preview / apply ---------------------------------------------------------


class CleaningPreviewRequest(BaseModel):
    operations: list[CleaningOperation] = Field(min_length=1, max_length=MAX_OPERATIONS)
    #: Profile a previous version instead of the original upload.
    source_version_id: uuid.UUID | None = None


class TypeChange(BaseModel):
    column: str
    before: DetectedType
    after: DetectedType


class OperationOutcome(BaseModel):
    """Per-operation effect, in execution order."""

    index: int
    operation: str
    column: str | None = None
    rows_affected: int = 0
    #: Set when an operation could not be applied but the run continued.
    warning: str | None = None


class CleaningPreviewResponse(BaseModel):
    dataset_id: uuid.UUID
    source_version_id: uuid.UUID | None = None

    original_row_count: int
    cleaned_row_count: int
    original_column_count: int
    cleaned_column_count: int

    missing_cells_before: int
    missing_cells_after: int
    duplicate_rows_before: int
    duplicate_rows_after: int

    rows_removed: int
    affected_columns: list[str] = Field(default_factory=list)
    type_changes: list[TypeChange] = Field(default_factory=list)
    operations: list[OperationOutcome] = Field(default_factory=list)
    #: Non-fatal problems the user should see before confirming.
    warnings: list[str] = Field(default_factory=list)
    #: Small sample of the cleaned result, for display only.
    sample_rows: list[dict[str, object]] = Field(default_factory=list)


class CleaningApplyRequest(BaseModel):
    operations: list[CleaningOperation] = Field(min_length=1, max_length=MAX_OPERATIONS)
    source_version_id: uuid.UUID | None = None
    #: Defaults to "<dataset name> (cleaned v<n>)".
    name: str | None = Field(default=None, min_length=1, max_length=255)


# --- Versions ----------------------------------------------------------------


class DatasetVersionResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    source_version_id: uuid.UUID | None = None
    version_number: int
    name: str
    file_size: int
    row_count: int
    column_count: int
    columns: list[dict[str, object]] | None = None
    operations: list[dict[str, object]] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


#: Paginated envelope returned by GET .../versions.
DatasetVersionListResponse = Page[DatasetVersionResponse]


class CleaningApplyResponse(BaseModel):
    version: DatasetVersionResponse
    preview: CleaningPreviewResponse
