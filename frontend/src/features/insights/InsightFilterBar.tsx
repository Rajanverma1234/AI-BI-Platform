/**
 * Filters for the insight list.
 *
 * Every option comes from the run's own `filters` payload, which the backend
 * builds from the dataset's actual values - there is no hard-coded list of
 * regions, categories or segments anywhere in this component.
 */

import type { BusinessInsight, InsightFilters } from '@/types/api';

export interface InsightFilterState {
  category: string;
  severity: string;
  priority: string;
  region: string;
  product: string;
  segment: string;
  period: string;
}

export const EMPTY_FILTERS: InsightFilterState = {
  category: '',
  severity: '',
  priority: '',
  region: '',
  product: '',
  segment: '',
  period: '',
};

/** Apply the selected filters. A finding with no dimension survives them. */
export function applyFilters(
  insights: BusinessInsight[],
  state: InsightFilterState,
  filters: InsightFilters,
): BusinessInsight[] {
  return insights.filter((insight) => {
    if (state.category && insight.category !== state.category) return false;
    if (state.severity && insight.severity !== state.severity) return false;
    if (state.priority && insight.priority !== state.priority) return false;

    // A dimension filter only excludes findings that are *about* that
    // dimension: a dataset-wide risk stays visible when filtering by region.
    if (state.region && insight.dimension === filters.region_column) {
      if (insight.dimension_value !== state.region) return false;
    }
    if (state.product && insight.dimension === filters.product_column) {
      if (insight.dimension_value !== state.product) return false;
    }
    if (state.segment && insight.category === 'customer') {
      if (insight.dimension_value !== state.segment) return false;
    }
    if (state.period && insight.dimension === filters.date_column) {
      if (insight.dimension_value !== state.period) return false;
    }
    return true;
  });
}

interface SelectProps {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  format?: (value: string) => string;
}

function FilterSelect({ label, value, options, onChange, format }: SelectProps) {
  if (options.length === 0) return null;
  return (
    <label className="field field--inline">
      <span className="muted small">{label}</span>
      <select
        className="input"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label={label}
      >
        <option value="">All</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {format ? format(option) : option}
          </option>
        ))}
      </select>
    </label>
  );
}

const humanise = (value: string) => value.replace(/_/g, ' ');

interface InsightFilterBarProps {
  filters: InsightFilters;
  state: InsightFilterState;
  onChange: (state: InsightFilterState) => void;
  resultCount: number;
  totalCount: number;
}

export function InsightFilterBar({
  filters,
  state,
  onChange,
  resultCount,
  totalCount,
}: InsightFilterBarProps) {
  const set = (key: keyof InsightFilterState) => (value: string) =>
    onChange({ ...state, [key]: value });

  const isFiltered = Object.values(state).some(Boolean);

  return (
    <div className="stack--narrow" data-testid="insight-filters">
      <div className="row">
        <FilterSelect
          label="Category"
          value={state.category}
          options={filters.categories}
          onChange={set('category')}
          format={humanise}
        />
        <FilterSelect
          label="Severity"
          value={state.severity}
          options={filters.severities}
          onChange={set('severity')}
        />
        <FilterSelect
          label="Priority"
          value={state.priority}
          options={filters.priorities}
          onChange={set('priority')}
        />
        <FilterSelect
          label={filters.region_column ?? 'Region'}
          value={state.region}
          options={filters.regions}
          onChange={set('region')}
        />
        <FilterSelect
          label={filters.product_column ?? 'Category'}
          value={state.product}
          options={filters.products}
          onChange={set('product')}
        />
        <FilterSelect
          label="Customer segment"
          value={state.segment}
          options={filters.customer_segments}
          onChange={set('segment')}
        />
        <FilterSelect
          label="Period"
          value={state.period}
          options={filters.periods}
          onChange={set('period')}
        />
      </div>

      <p className="muted small">
        Showing {resultCount.toLocaleString()} of {totalCount.toLocaleString()} findings.
        {isFiltered && (
          <>
            {' '}
            <button
              type="button"
              className="button button--ghost"
              onClick={() => onChange(EMPTY_FILTERS)}
            >
              Clear filters
            </button>
          </>
        )}
      </p>
    </div>
  );
}
