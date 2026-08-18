/** Shared visual tokens so every chart reads as one system. */

export const SERIES_COLORS = [
  '#5b8cff',
  '#37c98b',
  '#e0b341',
  '#ef6b6b',
  '#a78bfa',
  '#38bdf8',
  '#fb923c',
  '#f472b6',
] as const;

export const AXIS_COLOR = '#9aa4b6';
export const GRID_COLOR = '#262c38';
export const SURFACE_COLOR = '#171b23';
export const BORDER_COLOR = '#262c38';
export const TEXT_COLOR = '#e7eaf0';

export function seriesColor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

/** Tooltip styling shared by every recharts tooltip. */
export const TOOLTIP_STYLE = {
  contentStyle: {
    background: SURFACE_COLOR,
    border: `1px solid ${BORDER_COLOR}`,
    borderRadius: 8,
    color: TEXT_COLOR,
    fontSize: 12,
  },
  labelStyle: { color: AXIS_COLOR },
} as const;
