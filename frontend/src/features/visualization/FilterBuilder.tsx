/**
 * Builds a structured FilterSet. Type-aware: the operators offered depend on
 * the selected column's detected type, so a ">" on a text column is not even
 * reachable from the UI (the backend rejects it too).
 */

import type { DetectedType, FilterCondition, FilterOperator, FilterSet, PreviewColumn } from '@/types/api';

interface FilterBuilderProps {
  columns: PreviewColumn[];
  value: FilterSet;
  onChange: (filters: FilterSet) => void;
}

const NUMERIC: DetectedType[] = ['integer', 'float'];

const TEXT_OPERATORS: FilterOperator[] = [
  'equals',
  'not_equals',
  'contains',
  'is_null',
  'is_not_null',
];

const ORDERED_OPERATORS: FilterOperator[] = [
  'equals',
  'not_equals',
  'greater_than',
  'greater_or_equal',
  'less_than',
  'less_or_equal',
  'between',
  'is_null',
  'is_not_null',
];

const OPERATOR_LABELS: Record<FilterOperator, string> = {
  equals: 'equals',
  not_equals: 'does not equal',
  contains: 'contains',
  greater_than: '>',
  greater_or_equal: '≥',
  less_than: '<',
  less_or_equal: '≤',
  between: 'between',
  is_null: 'is empty',
  is_not_null: 'is not empty',
};

const NO_VALUE: FilterOperator[] = ['is_null', 'is_not_null'];

function operatorsFor(dtype: DetectedType | undefined): FilterOperator[] {
  if (!dtype) return TEXT_OPERATORS;
  return NUMERIC.includes(dtype) || dtype === 'datetime' ? ORDERED_OPERATORS : TEXT_OPERATORS;
}

export function FilterBuilder({ columns, value, onChange }: FilterBuilderProps) {
  function updateCondition(index: number, patch: Partial<FilterCondition>) {
    const conditions = value.conditions.map((condition, position) =>
      position === index ? { ...condition, ...patch } : condition,
    );
    onChange({ ...value, conditions });
  }

  function addCondition() {
    const first = columns[0];
    if (!first) return;
    onChange({
      ...value,
      conditions: [...value.conditions, { column: first.name, operator: 'equals', value: '' }],
    });
  }

  function removeCondition(index: number) {
    onChange({ ...value, conditions: value.conditions.filter((_, i) => i !== index) });
  }

  return (
    <div className="stack" data-testid="filter-builder">
      <div className="row">
        <label className="field field--inline">
          <span className="muted small">Combine with</span>
          <select
            className="input"
            value={value.logic}
            onChange={(event) =>
              onChange({ ...value, logic: event.target.value as FilterSet['logic'] })
            }
            aria-label="Filter logic"
          >
            <option value="and">AND — all must match</option>
            <option value="or">OR — any may match</option>
          </select>
        </label>
        <button type="button" className="button button--ghost" onClick={addCondition}>
          Add filter
        </button>
      </div>

      {value.conditions.length === 0 && (
        <p className="muted small">No filters — the whole dataset is used.</p>
      )}

      {value.conditions.map((condition, index) => {
        const dtype = columns.find((column) => column.name === condition.column)?.dtype;
        const operators = operatorsFor(dtype);
        const needsValue = !NO_VALUE.includes(condition.operator);

        return (
          <div className="row" key={`${condition.column}-${index}`}>
            <select
              className="input"
              value={condition.column}
              onChange={(event) => updateCondition(index, { column: event.target.value })}
              aria-label={`Filter column ${index + 1}`}
            >
              {columns.map((column) => (
                <option key={column.name} value={column.name}>
                  {column.name}
                </option>
              ))}
            </select>

            <select
              className="input"
              value={condition.operator}
              onChange={(event) =>
                updateCondition(index, { operator: event.target.value as FilterOperator })
              }
              aria-label={`Filter operator ${index + 1}`}
            >
              {operators.map((operator) => (
                <option key={operator} value={operator}>
                  {OPERATOR_LABELS[operator]}
                </option>
              ))}
            </select>

            {needsValue && (
              <input
                className="input"
                value={String(condition.value ?? '')}
                onChange={(event) => updateCondition(index, { value: event.target.value })}
                placeholder="value"
                aria-label={`Filter value ${index + 1}`}
              />
            )}

            {condition.operator === 'between' && (
              <input
                className="input"
                value={String(condition.value_to ?? '')}
                onChange={(event) => updateCondition(index, { value_to: event.target.value })}
                placeholder="and"
                aria-label={`Filter upper bound ${index + 1}`}
              />
            )}

            <button
              type="button"
              className="button button--ghost"
              onClick={() => removeCondition(index)}
              aria-label={`Remove filter ${index + 1}`}
            >
              Remove
            </button>
          </div>
        );
      })}
    </div>
  );
}
