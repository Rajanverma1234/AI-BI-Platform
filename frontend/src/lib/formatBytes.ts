const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const;

/** Human-readable file size, e.g. 1536 -> "1.5 KB". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';

  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), UNITS.length - 1);
  const value = bytes / 1024 ** exponent;
  // Whole numbers for bytes, one decimal above that.
  return `${exponent === 0 ? value : value.toFixed(1)} ${UNITS[exponent]}`;
}

/** Compact integer formatting for row/column counts. */
export function formatCount(value: number | null): string {
  return value === null ? '—' : value.toLocaleString();
}
