import { render, screen } from '@testing-library/react';
import { cloneElement, type ReactElement } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { ChartRenderer } from '@/features/visualization/ChartRenderer';
import type { ChartDataResponse } from '@/types/api';

// ResponsiveContainer measures its parent, which is always 0x0 in jsdom, so
// recharts would render nothing. Give the chart an explicit size instead.
vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>();
  return {
    ...actual,
    ResponsiveContainer: ({
      children,
    }: {
      children: ReactElement<{ width?: number; height?: number }>;
    }) => cloneElement(children, { width: 800, height: 400 }),
  };
});

function chart(overrides: Partial<ChartDataResponse> = {}): ChartDataResponse {
  return {
    chart_type: 'bar',
    title: 'Revenue by category',
    x_axis: 'product_category',
    y_axis: 'revenue',
    labels: ['Electronics', 'Grocery', 'Apparel'],
    series: [{ name: 'revenue', data: [120, 90, 60] }],
    points: [],
    boxes: [],
    metadata: {},
    ...overrides,
  };
}

describe('ChartRenderer axes', () => {
  // Regression: axes were wrapped in a fragment, which recharts does not scan,
  // so charts rendered bars with no category labels, values or axis titles.
  it.each(['bar', 'line', 'area'] as const)('renders axis titles for a %s chart', (type) => {
    render(<ChartRenderer chart={chart({ chart_type: type })} />);

    expect(screen.getByText('product_category')).toBeInTheDocument();
    expect(screen.getByText('revenue')).toBeInTheDocument();
  });

  it('renders every category label on the X axis', () => {
    render(<ChartRenderer chart={chart()} />);

    expect(screen.getByText('Electronics')).toBeInTheDocument();
    expect(screen.getByText('Grocery')).toBeInTheDocument();
    expect(screen.getByText('Apparel')).toBeInTheDocument();
  });

  it('renders numeric ticks on the Y axis', () => {
    const { container } = render(<ChartRenderer chart={chart()} />);

    const yAxis = container.querySelector('.recharts-yAxis');
    expect(yAxis).not.toBeNull();
    expect(yAxis?.textContent).toMatch(/\d/);
  });

  it('draws the cartesian grid', () => {
    const { container } = render(<ChartRenderer chart={chart()} />);

    expect(container.querySelector('.recharts-cartesian-grid')).not.toBeNull();
  });

  it('shows a legend only when there is more than one series', () => {
    const single = render(<ChartRenderer chart={chart()} />);
    expect(single.container.querySelector('.recharts-legend-wrapper')).toBeNull();
    single.unmount();

    const multi = render(
      <ChartRenderer
        chart={chart({
          series: [
            { name: 'north', data: [1, 2, 3] },
            { name: 'south', data: [3, 2, 1] },
          ],
        })}
      />,
    );
    expect(multi.container.querySelector('.recharts-legend-wrapper')).not.toBeNull();
  });

  it('renders scatter axes from points', () => {
    render(
      <ChartRenderer
        chart={chart({
          chart_type: 'scatter',
          labels: [],
          series: [],
          points: [
            { x: 1, y: 2 },
            { x: 3, y: 4 },
          ],
        })}
      />,
    );

    expect(screen.getByText('product_category')).toBeInTheDocument();
    expect(screen.getByText('revenue')).toBeInTheDocument();
  });

  it('falls back to an empty state when there is nothing to plot', () => {
    render(<ChartRenderer chart={chart({ labels: [], series: [] })} />);

    expect(screen.getByTestId('chart-empty')).toBeInTheDocument();
  });

  it('renders a box plot with its group labels', () => {
    render(
      <ChartRenderer
        chart={chart({
          chart_type: 'box',
          labels: [],
          series: [],
          boxes: [
            {
              label: 'Electronics',
              minimum: 1,
              q1: 2,
              median: 3,
              q3: 4,
              maximum: 5,
              outlier_count: 0,
            },
          ],
        })}
      />,
    );

    expect(screen.getByTestId('box-plot')).toBeInTheDocument();
    expect(screen.getByText('Electronics')).toBeInTheDocument();
  });
});
