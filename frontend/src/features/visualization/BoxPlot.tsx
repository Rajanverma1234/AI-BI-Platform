/**
 * Box plot rendered as inline SVG.
 *
 * Recharts has no box-plot primitive, and the brief allows only one charting
 * library, so this draws the five-number summary directly rather than adding a
 * second dependency. The backend supplies the statistics.
 */

import { AXIS_COLOR, GRID_COLOR, seriesColor } from '@/features/visualization/chartTheme';
import type { BoxPlotStats } from '@/types/api';

interface BoxPlotProps {
  boxes: BoxPlotStats[];
  height?: number;
}

const PADDING = { top: 16, right: 16, bottom: 48, left: 56 };

export function BoxPlot({ boxes, height = 320 }: BoxPlotProps) {
  const width = Math.max(320, boxes.length * 110 + PADDING.left + PADDING.right);
  const plotHeight = height - PADDING.top - PADDING.bottom;

  const lowest = Math.min(...boxes.map((box) => box.minimum));
  const highest = Math.max(...boxes.map((box) => box.maximum));
  // Guard against a zero-height domain when every value is identical.
  const span = highest - lowest || 1;

  const toY = (value: number) => PADDING.top + plotHeight - ((value - lowest) / span) * plotHeight;
  const bandWidth = (width - PADDING.left - PADDING.right) / boxes.length;
  const boxWidth = Math.min(56, bandWidth * 0.6);

  const ticks = [lowest, lowest + span / 2, highest];

  return (
    <div className="table-scroll">
      <svg
        width={width}
        height={height}
        role="img"
        aria-label="Box plot"
        data-testid="box-plot"
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PADDING.left}
              x2={width - PADDING.right}
              y1={toY(tick)}
              y2={toY(tick)}
              stroke={GRID_COLOR}
            />
            <text x={8} y={toY(tick) + 4} fill={AXIS_COLOR} fontSize={11}>
              {tick.toFixed(1)}
            </text>
          </g>
        ))}

        {boxes.map((box, index) => {
          const centre = PADDING.left + bandWidth * index + bandWidth / 2;
          const left = centre - boxWidth / 2;
          const colour = seriesColor(index);
          const boxTop = toY(box.q3);
          const boxBottom = toY(box.q1);

          return (
            <g key={box.label}>
              {/* Whiskers */}
              <line
                x1={centre}
                x2={centre}
                y1={toY(box.maximum)}
                y2={boxTop}
                stroke={colour}
              />
              <line
                x1={centre}
                x2={centre}
                y1={boxBottom}
                y2={toY(box.minimum)}
                stroke={colour}
              />
              <line
                x1={centre - boxWidth / 4}
                x2={centre + boxWidth / 4}
                y1={toY(box.maximum)}
                y2={toY(box.maximum)}
                stroke={colour}
              />
              <line
                x1={centre - boxWidth / 4}
                x2={centre + boxWidth / 4}
                y1={toY(box.minimum)}
                y2={toY(box.minimum)}
                stroke={colour}
              />

              {/* Interquartile box */}
              <rect
                x={left}
                y={boxTop}
                width={boxWidth}
                height={Math.max(boxBottom - boxTop, 1)}
                fill={colour}
                fillOpacity={0.25}
                stroke={colour}
              />
              {/* Median */}
              <line
                x1={left}
                x2={left + boxWidth}
                y1={toY(box.median)}
                y2={toY(box.median)}
                stroke={colour}
                strokeWidth={2}
              />

              <title>
                {`${box.label}: min ${box.minimum}, Q1 ${box.q1}, median ${box.median}, ` +
                  `Q3 ${box.q3}, max ${box.maximum}, ${box.outlier_count} outlier(s)`}
              </title>

              <text
                x={centre}
                y={height - PADDING.bottom + 20}
                fill={AXIS_COLOR}
                fontSize={11}
                textAnchor="middle"
              >
                {box.label.length > 12 ? `${box.label.slice(0, 12)}…` : box.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
