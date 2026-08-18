/**
 * Correlation matrix rendered as a coloured grid.
 *
 * Diverging scale: blue for positive, red for negative, neutral near zero.
 * Undefined pairs render as a dash rather than a misleading colour.
 */

import type { CorrelationResponse } from '@/types/api';

interface CorrelationHeatmapProps {
  correlation: CorrelationResponse;
}

/** Map a coefficient in [-1, 1] onto a background colour. */
function cellColour(value: number | null): string {
  if (value === null) return 'transparent';
  const intensity = Math.min(Math.abs(value), 1) * 0.75;
  return value >= 0
    ? `rgba(91, 140, 255, ${intensity})`
    : `rgba(239, 107, 107, ${intensity})`;
}

export function CorrelationHeatmap({ correlation }: CorrelationHeatmapProps) {
  const { columns, matrix } = correlation;

  return (
    <div className="table-scroll">
      <table className="table heatmap" data-testid="correlation-heatmap">
        <thead>
          <tr>
            <th scope="col" />
            {columns.map((column) => (
              <th key={column} scope="col" className="heatmap__head">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrix.map((row, rowIndex) => (
            <tr key={columns[rowIndex]}>
              <th scope="row">{columns[rowIndex]}</th>
              {row.map((value, columnIndex) => (
                <td
                  key={`${columns[rowIndex]}-${columns[columnIndex]}`}
                  className="heatmap__cell"
                  style={{ background: cellColour(value) }}
                  title={`${columns[rowIndex]} vs ${columns[columnIndex]}: ${
                    value === null ? 'undefined' : value.toFixed(3)
                  }`}
                >
                  {value === null ? '—' : value.toFixed(2)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
