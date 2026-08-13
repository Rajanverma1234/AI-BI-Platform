"""Deterministic cleaning operations.

Each operation is a pure function of (DataFrame, parameters) -> (DataFrame,
outcome). Running the same pipeline over the same input always produces the
same output, which is what makes preview and apply agree and versions
reproducible. No LLM is involved in generating or executing operations.

Operations never mutate the caller's frame; each returns a new one.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.schemas.cleaning import (
    CleaningOperation,
    ConvertibleType,
    ConvertTypeOperation,
    DropColumnOperation,
    DropMissingRowsOperation,
    FillMissingOperation,
    HandleOutliersOperation,
    MissingStrategy,
    OperationOutcome,
    OutlierAction,
    OutlierMethod,
    RemoveDuplicatesOperation,
    RenameColumnOperation,
    ReorderColumnsOperation,
)


def _require_column(frame: pd.DataFrame, column: str) -> None:
    if column not in frame.columns:
        raise ValidationError(f"Column '{column}' does not exist in this dataset.")


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.dropna().empty:
        raise ValidationError(f"Column '{column}' has no numeric values to work with.")
    return values


# --- Missing values ----------------------------------------------------------


def _fill_value(frame: pd.DataFrame, op: FillMissingOperation) -> Any:
    """Resolve the replacement value for a fill strategy."""
    series = frame[op.column]

    if op.strategy is MissingStrategy.CUSTOM:
        if op.value is None:
            raise ValidationError(
                f"A custom value is required to fill '{op.column}'."
            )
        return op.value

    if op.strategy in (MissingStrategy.MEAN, MissingStrategy.MEDIAN):
        numeric = pd.to_numeric(series, errors="coerce")
        if numeric.dropna().empty:
            raise ValidationError(
                f"Column '{op.column}' has no numeric values, so "
                f"'{op.strategy.value}' cannot be computed."
            )
        return numeric.mean() if op.strategy is MissingStrategy.MEAN else numeric.median()

    if op.strategy is MissingStrategy.MODE:
        modes = series.dropna().mode()
        if modes.empty:
            raise ValidationError(f"Column '{op.column}' has no values to derive a mode from.")
        return modes.iloc[0]

    return None  # forward/backward fill handled by the caller


def apply_fill_missing(
    frame: pd.DataFrame, op: FillMissingOperation
) -> tuple[pd.DataFrame, int]:
    _require_column(frame, op.column)
    result = frame.copy()
    missing_before = int(result[op.column].isna().sum())
    if missing_before == 0:
        return result, 0

    if op.strategy is MissingStrategy.FORWARD_FILL:
        result[op.column] = result[op.column].ffill()
    elif op.strategy is MissingStrategy.BACKWARD_FILL:
        result[op.column] = result[op.column].bfill()
    else:
        result[op.column] = result[op.column].fillna(_fill_value(frame, op))

    filled = missing_before - int(result[op.column].isna().sum())
    return result, filled


def apply_drop_missing_rows(
    frame: pd.DataFrame, op: DropMissingRowsOperation
) -> tuple[pd.DataFrame, int]:
    if op.column is not None:
        _require_column(frame, op.column)
        result = frame.dropna(subset=[op.column])
    else:
        result = frame.dropna()
    return result.reset_index(drop=True), int(len(frame) - len(result))


# --- Duplicates --------------------------------------------------------------


def apply_remove_duplicates(
    frame: pd.DataFrame, op: RemoveDuplicatesOperation
) -> tuple[pd.DataFrame, int]:
    if op.subset:
        for column in op.subset:
            _require_column(frame, column)
    result = frame.drop_duplicates(subset=op.subset, keep="first")
    return result.reset_index(drop=True), int(len(frame) - len(result))


# --- Type conversion ---------------------------------------------------------


_TRUE_VALUES = {"true", "yes", "y", "1", "t"}
_FALSE_VALUES = {"false", "no", "n", "0", "f"}


def _convert_series(series: pd.Series, to_type: ConvertibleType) -> pd.Series:
    """Convert a column, marking unconvertible values as NaN/NaT."""
    if to_type is ConvertibleType.STRING:
        return series.astype("string")

    if to_type in (ConvertibleType.INTEGER, ConvertibleType.FLOAT):
        numeric = pd.to_numeric(series, errors="coerce")
        if to_type is ConvertibleType.INTEGER:
            # Nullable Int64 so a column with gaps stays integral.
            return numeric.round().astype("Int64")
        return numeric.astype("float64")

    if to_type is ConvertibleType.BOOLEAN:
        text = series.astype(str).str.strip().str.lower()
        mapped = text.map(
            lambda value: True
            if value in _TRUE_VALUES
            else (False if value in _FALSE_VALUES else pd.NA)
        )
        return mapped.astype("boolean")

    parsed = pd.to_datetime(series, errors="coerce", format="mixed")
    if to_type is ConvertibleType.DATE:
        return parsed.dt.normalize()
    return parsed


def validate_conversion(series: pd.Series, to_type: ConvertibleType) -> int:
    """Return how many non-null values would fail to convert."""
    non_null = series.dropna()
    if non_null.empty:
        return 0
    converted = _convert_series(non_null, to_type)
    return int(converted.isna().sum())


def apply_convert_type(
    frame: pd.DataFrame, op: ConvertTypeOperation
) -> tuple[pd.DataFrame, int]:
    _require_column(frame, op.column)

    failures = validate_conversion(frame[op.column], op.to_type)
    if failures and not op.errors_to_null:
        # Refuse rather than silently turning real data into nulls.
        raise ValidationError(
            f"{failures} value(s) in '{op.column}' cannot be converted to "
            f"{op.to_type.value}. Re-run allowing invalid values to become empty, "
            "or clean the column first."
        )

    result = frame.copy()
    result[op.column] = _convert_series(result[op.column], op.to_type)
    return result, failures


# --- Column operations -------------------------------------------------------


def apply_rename_column(
    frame: pd.DataFrame, op: RenameColumnOperation
) -> tuple[pd.DataFrame, int]:
    _require_column(frame, op.column)
    if op.new_name != op.column and op.new_name in frame.columns:
        raise ValidationError(f"A column named '{op.new_name}' already exists.")
    return frame.rename(columns={op.column: op.new_name}), 0


def apply_drop_column(frame: pd.DataFrame, op: DropColumnOperation) -> tuple[pd.DataFrame, int]:
    _require_column(frame, op.column)
    if len(frame.columns) == 1:
        raise ValidationError("A dataset must keep at least one column.")
    return frame.drop(columns=[op.column]), 0


def apply_reorder_columns(
    frame: pd.DataFrame, op: ReorderColumnsOperation
) -> tuple[pd.DataFrame, int]:
    for column in op.order:
        _require_column(frame, column)
    if len(set(op.order)) != len(op.order):
        raise ValidationError("The column order contains duplicates.")

    # Columns the caller did not mention keep their relative order at the end.
    remaining = [column for column in frame.columns if column not in op.order]
    return frame[[*op.order, *remaining]], 0


# --- Outliers ----------------------------------------------------------------


def outlier_mask(series: pd.Series, method: OutlierMethod, threshold: float) -> pd.Series:
    """Boolean mask of outlying rows. Deterministic for a given input."""
    values = pd.to_numeric(series, errors="coerce")

    if method is OutlierMethod.IQR:
        q1 = values.quantile(0.25)
        q3 = values.quantile(0.75)
        iqr = q3 - q1
        if pd.isna(iqr) or iqr == 0:
            return pd.Series(False, index=series.index)
        lower = q1 - threshold * iqr
        upper = q3 + threshold * iqr
    else:
        mean = values.mean()
        std = values.std()
        if pd.isna(std) or std == 0:
            return pd.Series(False, index=series.index)
        lower = mean - threshold * std
        upper = mean + threshold * std

    return ((values < lower) | (values > upper)).fillna(False)


def count_outliers(series: pd.Series, method: OutlierMethod, threshold: float) -> int:
    return int(outlier_mask(series, method, threshold).sum())


def apply_handle_outliers(
    frame: pd.DataFrame, op: HandleOutliersOperation
) -> tuple[pd.DataFrame, int]:
    _require_column(frame, op.column)
    values = _numeric_series(frame, op.column)

    mask = outlier_mask(values, op.method, op.threshold)
    affected = int(mask.sum())
    if affected == 0:
        return frame.copy(), 0

    if op.action is OutlierAction.REMOVE:
        return frame.loc[~mask].reset_index(drop=True), affected

    # Cap/winsorise at the same bounds the mask was derived from.
    if op.method is OutlierMethod.IQR:
        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        iqr = q3 - q1
        lower, upper = q1 - op.threshold * iqr, q3 + op.threshold * iqr
    else:
        mean, std = values.mean(), values.std()
        lower, upper = mean - op.threshold * std, mean + op.threshold * std

    result = frame.copy()
    result[op.column] = values.clip(lower=lower, upper=upper)
    return result, affected


# --- Pipeline ----------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    "fill_missing": apply_fill_missing,
    "drop_missing_rows": apply_drop_missing_rows,
    "remove_duplicates": apply_remove_duplicates,
    "convert_type": apply_convert_type,
    "rename_column": apply_rename_column,
    "drop_column": apply_drop_column,
    "reorder_columns": apply_reorder_columns,
    "handle_outliers": apply_handle_outliers,
}


def run_pipeline(
    frame: pd.DataFrame,
    operations: list[CleaningOperation],
) -> tuple[pd.DataFrame, list[OperationOutcome], list[str]]:
    """Execute operations in order.

    Returns the cleaned frame, a per-operation outcome list, and any warnings.
    A ValidationError from an operation aborts the run so the user can correct
    the pipeline - a half-applied pipeline would not be reproducible.
    """
    current = frame
    outcomes: list[OperationOutcome] = []
    warnings: list[str] = []

    for index, operation in enumerate(operations):
        handler = _HANDLERS.get(operation.operation)
        if handler is None:  # pragma: no cover - the union prevents this
            raise ValidationError(f"Unknown operation '{operation.operation}'.")

        current, affected = handler(current, operation)

        warning: str | None = None
        if operation.operation == "convert_type" and affected:
            warning = (
                f"{affected} value(s) in '{operation.column}' could not be converted "
                "and became empty."
            )
            warnings.append(warning)

        outcomes.append(
            OperationOutcome(
                index=index,
                operation=operation.operation,
                column=getattr(operation, "column", None),
                rows_affected=affected,
                warning=warning,
            )
        )

    return current, outcomes, warnings
