/**
 * Renders any supported chart from the backend's structured data.
 *
 * Presentation only: it never fetches or aggregates. Recharts is the single
 * charting library; the box plot is inline SVG rather than a second dependency.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { EmptyState } from '@/components/ui';
import { BoxPlot } from '@/features/visualization/BoxPlot';
import {
  AXIS_COLOR,
  GRID_COLOR,
  TOOLTIP_STYLE,
  seriesColor,
} from '@/features/visualization/chartTheme';
import type { ChartDataResponse } from '@/types/api';

interface ChartRendererProps {
  chart: ChartDataResponse;
  height?: number;
}

/** Pivot the label/series arrays into the row shape recharts expects. */
function toRows(chart: ChartDataResponse): Record<string, string | number | null>[] {
  return chart.labels.map((label, index) => {
    const row: Record<string, string | number | null> = { label };
    for (const series of chart.series) {
      row[series.name] = series.data[index] ?? null;
    }
    return row;
  });
}

function hasData(chart: ChartDataResponse): boolean {
  if (chart.chart_type === 'scatter') return chart.points.length > 0;
  if (chart.chart_type === 'box') return chart.boxes.length > 0;
  return chart.labels.length > 0 && chart.series.length > 0;
}

const AXIS_PROPS = { stroke: AXIS_COLOR, tick: { fill: AXIS_COLOR, fontSize: 11 } };

export function ChartRenderer({ chart, height = 340 }: ChartRendererProps) {
  if (!hasData(chart)) {
    return (
      <EmptyState
        title="Nothing to plot"
        hint="This configuration produced no data points. Try different columns or filters."
        testId="chart-empty"
      />
    );
  }

  if (chart.chart_type === 'box') {
    return <BoxPlot boxes={chart.boxes} height={height} />;
  }

  if (chart.chart_type === 'scatter') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <ScatterChart margin={{ top: 12, right: 16, bottom: 32, left: 8 }}>
          <CartesianGrid stroke={GRID_COLOR} />
          <XAxis
            type="number"
            dataKey="x"
            name={chart.x_axis ?? 'x'}
            label={{ value: chart.x_axis ?? '', position: 'insideBottom', offset: -18, fill: AXIS_COLOR }}
            {...AXIS_PROPS}
          />
          <YAxis
            type="number"
            dataKey="y"
            name={chart.y_axis ?? 'y'}
            label={{ value: chart.y_axis ?? '', angle: -90, position: 'insideLeft', fill: AXIS_COLOR }}
            {...AXIS_PROPS}
          />
          <Tooltip cursor={{ strokeDasharray: '3 3' }} {...TOOLTIP_STYLE} />
          <Scatter data={chart.points} fill={seriesColor(0)} />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  if (chart.chart_type === 'pie' || chart.chart_type === 'donut') {
    const series = chart.series[0];
    const pieData = chart.labels.map((label, index) => ({
      name: label,
      value: series?.data[index] ?? 0,
    }));

    return (
      <ResponsiveContainer width="100%" height={height}>
        <PieChart>
          <Tooltip {...TOOLTIP_STYLE} />
          <Legend />
          <Pie
            data={pieData}
            dataKey="value"
            nameKey="name"
            // A donut is a pie with a hole; same data, different inner radius.
            innerRadius={chart.chart_type === 'donut' ? '55%' : 0}
            outerRadius="80%"
          >
            {pieData.map((entry, index) => (
              <Cell key={entry.name} fill={seriesColor(index)} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
    );
  }

  const rows = toRows(chart);
  // Room for the rotated Y-axis title on the left and the X-axis title below.
  const margin = { top: 12, right: 16, bottom: 48, left: 24 };

  /**
   * Axis/grid/tooltip elements as an ARRAY, not a fragment.
   *
   * Recharts discovers these by scanning the chart's direct children.
   * React.Children flattens arrays but not fragments, so wrapping them in <>…</>
   * makes recharts ignore them and the chart renders bars with no axes at all.
   */
  const axes = [
    <CartesianGrid key="grid" stroke={GRID_COLOR} vertical={false} />,
    <XAxis
      key="x-axis"
      dataKey="label"
      label={{
        value: chart.x_axis ?? '',
        position: 'insideBottom',
        offset: -12,
        fill: AXIS_COLOR,
      }}
      {...AXIS_PROPS}
    />,
    <YAxis
      key="y-axis"
      width={72}
      label={{
        value: chart.y_axis ?? '',
        angle: -90,
        position: 'insideLeft',
        offset: 4,
        fill: AXIS_COLOR,
        style: { textAnchor: 'middle' },
      }}
      {...AXIS_PROPS}
    />,
    <Tooltip key="tooltip" {...TOOLTIP_STYLE} />,
    ...(chart.series.length > 1 ? [<Legend key="legend" />] : []),
  ];

  if (chart.chart_type === 'line') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={rows} margin={margin}>
          {axes}
          {chart.series.map((series, index) => (
            <Line
              key={series.name}
              type="monotone"
              dataKey={series.name}
              stroke={seriesColor(index)}
              dot={false}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (chart.chart_type === 'area') {
    return (
      <ResponsiveContainer width="100%" height={height}>
        <AreaChart data={rows} margin={margin}>
          {axes}
          {chart.series.map((series, index) => (
            <Area
              key={series.name}
              type="monotone"
              dataKey={series.name}
              stroke={seriesColor(index)}
              fill={seriesColor(index)}
              fillOpacity={0.25}
              connectNulls
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  // bar and histogram share the same rendering.
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={margin}>
        {axes}
        {chart.series.map((series, index) => (
          <Bar key={series.name} dataKey={series.name} fill={seriesColor(index)} />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}
