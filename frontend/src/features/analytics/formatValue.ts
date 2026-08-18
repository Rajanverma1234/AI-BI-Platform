/** Formats KPI values from the definition's format hints. */

import type { KpiFormat } from '@/types/api';

export function formatValue(value: number | null, format?: KpiFormat): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';

  const decimals = format?.decimals ?? 2;
  const style = format?.style ?? 'number';

  const body =
    style === 'integer'
      ? Math.round(value).toLocaleString()
      : value.toLocaleString(undefined, {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals,
        });

  const prefix = format?.prefix ?? (style === 'currency' ? '₹' : '');
  const suffix = format?.suffix ?? (style === 'percent' ? '%' : '');
  return `${prefix}${body}${suffix}`;
}

/** Signed percentage, e.g. "+20.0%". Null renders as a dash. */
export function formatChange(value: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(1)}%`;
}

export function changeTone(value: number | null): 'up' | 'down' | 'flat' {
  if (value === null || value === undefined || Number.isNaN(value) || value === 0) return 'flat';
  return value > 0 ? 'up' : 'down';
}
