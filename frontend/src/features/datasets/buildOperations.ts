/**
 * Turns the cleaning form's selections into an ordered pipeline.
 *
 * Order matters and is deliberate: column removals first (so later steps skip
 * dropped columns), then type conversions, then missing-value handling, then
 * outliers, and duplicates last (so rows made identical by filling are caught).
 */

import type {
  CleaningOperation,
  ConvertibleType,
  MissingStrategy,
  OutlierAction,
  OutlierMethod,
} from '@/types/api';

export type MissingChoice = 'keep' | MissingStrategy | 'remove_rows';
export type OutlierChoice = 'keep' | OutlierAction;

export interface ColumnSelection {
  missing: MissingChoice;
  /** Used when `missing` is "custom". */
  customValue: string;
  outlier: OutlierChoice;
  outlierMethod: OutlierMethod;
  convertTo: ConvertibleType | '';
  drop: boolean;
  rename: string;
}

export const DEFAULT_SELECTION: ColumnSelection = {
  missing: 'keep',
  customValue: '',
  outlier: 'keep',
  outlierMethod: 'iqr',
  convertTo: '',
  drop: false,
  rename: '',
};

export interface BuildInput {
  selections: Record<string, ColumnSelection>;
  removeDuplicates: boolean;
  /** Allows a conversion to null out values it cannot parse. */
  convertErrorsToNull: boolean;
}

export function buildOperations({
  selections,
  removeDuplicates,
  convertErrorsToNull,
}: BuildInput): CleaningOperation[] {
  const operations: CleaningOperation[] = [];
  const entries = Object.entries(selections);

  // 1. Drops — everything after this ignores removed columns.
  for (const [column, selection] of entries) {
    if (selection.drop) operations.push({ operation: 'drop_column', column });
  }

  const kept = entries.filter(([, selection]) => !selection.drop);

  // 2. Renames, before other operations reference the new name.
  for (const [column, selection] of kept) {
    const newName = selection.rename.trim();
    if (newName && newName !== column) {
      operations.push({ operation: 'rename_column', column, new_name: newName });
    }
  }

  /** Operations after a rename must target the new name. */
  const effectiveName = (column: string, selection: ColumnSelection) => {
    const renamed = selection.rename.trim();
    return renamed && renamed !== column ? renamed : column;
  };

  // 3. Type conversions.
  for (const [column, selection] of kept) {
    if (selection.convertTo) {
      operations.push({
        operation: 'convert_type',
        column: effectiveName(column, selection),
        to_type: selection.convertTo,
        errors_to_null: convertErrorsToNull,
      });
    }
  }

  // 4. Missing values.
  for (const [column, selection] of kept) {
    if (selection.missing === 'keep') continue;
    const name = effectiveName(column, selection);

    if (selection.missing === 'remove_rows') {
      operations.push({ operation: 'drop_missing_rows', column: name });
      continue;
    }

    operations.push({
      operation: 'fill_missing',
      column: name,
      strategy: selection.missing,
      ...(selection.missing === 'custom' ? { value: selection.customValue } : {}),
    });
  }

  // 5. Outliers.
  for (const [column, selection] of kept) {
    if (selection.outlier === 'keep') continue;
    operations.push({
      operation: 'handle_outliers',
      column: effectiveName(column, selection),
      method: selection.outlierMethod,
      action: selection.outlier,
      threshold: selection.outlierMethod === 'iqr' ? 1.5 : 3,
    });
  }

  // 6. Duplicates last: filling missing values can create new duplicates.
  if (removeDuplicates) operations.push({ operation: 'remove_duplicates' });

  return operations;
}
