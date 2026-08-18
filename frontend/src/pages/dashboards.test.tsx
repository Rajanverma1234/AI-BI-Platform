import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { cloneElement, type ReactElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearAuthToken, setAuthToken } from '@/lib/authToken';
import {
  authenticatedHandlers,
  type Handlers,
  mockApi,
  page,
  TEST_PROJECT,
  TEST_WORKSPACE,
} from '@/test/mockApi';
import { renderApp } from '@/test/renderWithProviders';
import type {
  DashboardData,
  DashboardDetail,
  DashboardFilterOptions,
  DashboardTemplateList,
} from '@/types/api';

// ResponsiveContainer measures its parent, which is always 0x0 in jsdom, and
// needs a ResizeObserver that jsdom does not provide. Same approach as
// ChartRenderer.test.tsx: give the chart an explicit size instead.
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

const DATASET_ID = '88888888-8888-4888-8888-888888888888';
const DASHBOARD_ID = '99999999-9999-4999-8999-999999999999';
const PROJECT_PATH = `/workspaces/${TEST_WORKSPACE.id}/projects/${TEST_PROJECT.id}`;
const LIST_PATH = `${PROJECT_PATH}/dashboards`;
const DETAIL_PATH = `${LIST_PATH}/${DASHBOARD_ID}`;

const DATASET = {
  id: DATASET_ID,
  project_id: TEST_PROJECT.id,
  name: 'Sales export',
  original_filename: 'sales.csv',
  file_type: 'csv',
  file_size: 2048,
  status: 'ready',
  row_count: 5000,
  column_count: 12,
  columns: null,
  error_message: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const DASHBOARD = {
  id: DASHBOARD_ID,
  project_id: TEST_PROJECT.id,
  dataset_id: DATASET_ID,
  dataset_version_id: null,
  name: 'Sales performance',
  description: 'Revenue at a glance',
  layout_columns: 2,
  filters: null,
  widget_count: 3,
  created_at: '2026-08-15T09:00:00Z',
  updated_at: '2026-08-15T09:00:00Z',
};

const DETAIL: DashboardDetail = {
  dashboard: DASHBOARD,
  version_label: 'Original dataset',
  dataset_name: 'Sales export',
  widgets: [],
};

const TEMPLATES: DashboardTemplateList = {
  dataset_id: DATASET_ID,
  version_id: null,
  templates: [
    {
      key: 'sales',
      name: 'Sales dashboard',
      description: 'Headline figures and where the value sits.',
      layout_columns: 2,
      widgets: [],
      unavailable: [
        { widget: 'Average rating', reason: 'Needs a rating column, which was not detected.' },
      ],
    },
  ],
  suggestions: [],
};

const FILTERS: DashboardFilterOptions = {
  dataset_id: DATASET_ID,
  version_id: null,
  fields: [
    {
      column: 'region',
      kind: 'categorical',
      values: ['North', 'South'],
      minimum: null,
      maximum: null,
      role: 'region',
    },
    {
      column: 'total_amount',
      kind: 'numeric',
      values: [],
      minimum: 10,
      maximum: 900,
      role: 'revenue',
    },
  ],
};

const DATA: DashboardData = {
  dashboard_id: DASHBOARD_ID,
  name: 'Sales performance',
  description: 'Revenue at a glance',
  dataset_id: DATASET_ID,
  dataset_name: 'Sales export',
  version_id: null,
  version_label: 'Original dataset',
  layout_columns: 2,
  row_count: 5000,
  refreshed_at: '2026-08-15T10:00:00Z',
  applied_filters: null,
  filtered_row_count: 5000,
  widgets: [
    {
      widget_id: 'w-kpi',
      widget_type: 'kpi',
      title: 'Total revenue',
      position: { x: 0, y: 0, width: 1, height: 1 },
      status: 'ok',
      error: null,
      kpi: {
        result: {
          name: 'Total revenue',
          description: null,
          value: 1084000,
          available: true,
          reason: null,
          metric: 'sum',
          column: 'total_amount',
          format: { style: 'number', decimals: 2 },
          comparison: null,
          groups: [],
        },
      },
      chart: null,
      table: null,
      insight: null,
      recommendation: null,
      text: null,
      nlq: null,
      advanced: null,
    },
    {
      widget_id: 'w-chart',
      widget_type: 'chart',
      title: 'Revenue by region',
      position: { x: 1, y: 0, width: 1, height: 2 },
      status: 'ok',
      error: null,
      kpi: null,
      chart: {
        chart_type: 'bar',
        title: null,
        x_axis: 'region',
        y_axis: 'total_amount',
        labels: ['North', 'South'],
        series: [{ name: 'total_amount', data: [620000, 464000] }],
        points: [],
        boxes: [],
        metadata: {},
      },
      table: null,
      insight: null,
      recommendation: null,
      text: null,
      nlq: null,
      advanced: null,
    },
    {
      widget_id: 'w-broken',
      widget_type: 'chart',
      title: 'Broken widget',
      position: { x: 0, y: 1, width: 1, height: 1 },
      status: 'error',
      error: "The dataset has no column called 'not_a_column'.",
      kpi: null,
      chart: null,
      table: null,
      insight: null,
      recommendation: null,
      text: null,
      nlq: null,
      advanced: null,
    },
  ],
};

function listHandlers(extra: Handlers = {}): Handlers {
  return authenticatedHandlers({
    [`GET /projects/${TEST_PROJECT.id}/dashboards`]: { body: page([DASHBOARD]) },
    [`GET /projects/${TEST_PROJECT.id}/datasets`]: { body: page([DATASET]) },
    [`GET /projects/${TEST_PROJECT.id}/dashboards/templates`]: { body: TEMPLATES },
    ...extra,
  });
}

function detailHandlers(extra: Handlers = {}): Handlers {
  return authenticatedHandlers({
    [`GET /dashboards/${DASHBOARD_ID}`]: { body: DETAIL },
    [`GET /dashboards/${DASHBOARD_ID}/filters`]: { body: FILTERS },
    [`GET /projects/${TEST_PROJECT.id}/datasets/${DATASET_ID}/versions`]: { body: page([]) },
    [`POST /dashboards/${DASHBOARD_ID}/refresh`]: { body: DATA },
    ...extra,
  });
}

describe('DashboardsPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
    setAuthToken('a-valid-access-token');
  });

  it('lists the project dashboards', async () => {
    mockApi(listHandlers());

    renderApp(LIST_PATH);

    expect(await screen.findByTestId('dashboard-list')).toHaveTextContent('Sales performance');
  });

  it('shows an empty state when the project has none', async () => {
    mockApi(listHandlers({ [`GET /projects/${TEST_PROJECT.id}/dashboards`]: { body: page([]) } }));

    renderApp(LIST_PATH);

    expect(await screen.findByTestId('no-dashboards')).toBeInTheDocument();
  });

  it('explains which template widgets the dataset cannot support', async () => {
    mockApi(listHandlers());

    renderApp(LIST_PATH);

    // The template list arrives after the dataset list, so wait for the option
    // to exist before selecting it.
    await waitFor(() =>
      expect(screen.getByRole('option', { name: /Sales dashboard/ })).toBeInTheDocument(),
    );
    await userEvent.selectOptions(screen.getByLabelText('Start from'), 'sales');

    const note = await screen.findByTestId('template-note');
    expect(note).toHaveTextContent('Average rating');
    expect(note).toHaveTextContent('Needs a rating column');
  });
});

describe('DashboardDetailPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
    setAuthToken('a-valid-access-token');
  });

  it('always states the dataset and version it is built on', async () => {
    mockApi(detailHandlers());

    renderApp(DETAIL_PATH);

    expect(await screen.findByTestId('dashboard-source')).toHaveTextContent('Sales export');
    expect(screen.getByTestId('dashboard-source')).toHaveTextContent('Original dataset');
  });

  it('renders each resolved widget with the existing components', async () => {
    mockApi(detailHandlers());

    renderApp(DETAIL_PATH);

    const grid = await screen.findByTestId('dashboard-grid');
    expect(within(grid).getByTestId('widget-w-kpi')).toHaveTextContent('Total revenue');
    // Grouping separators follow the viewer's locale, so match the digits.
    expect(within(grid).getByTestId('widget-w-kpi').textContent).toMatch(/1[,\d]*000\.00/);
    expect(within(grid).getByTestId('widget-w-chart')).toBeInTheDocument();
  });

  it('keeps working when one widget fails', async () => {
    mockApi(detailHandlers());

    renderApp(DETAIL_PATH);

    const broken = await screen.findByTestId('widget-error-w-broken');
    expect(broken).toHaveTextContent('Unable to load this widget.');
    expect(broken).toHaveTextContent("no column called 'not_a_column'");
    expect(within(broken).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
    // The other widgets are unaffected.
    expect(screen.getByTestId('widget-w-kpi')).toHaveTextContent('Total revenue');
    expect(screen.getByTestId('widget-w-kpi').textContent).toMatch(/1[,\d]*000\.00/);
  });

  it('offers filters built from the dataset, not a fixed list', async () => {
    mockApi(detailHandlers());

    renderApp(DETAIL_PATH);

    const filters = await screen.findByTestId('dashboard-filters');
    const select = within(filters).getByLabelText('region');
    expect(within(select).getByRole('option', { name: 'North' })).toBeInTheDocument();
    // A numeric column is not offered as a categorical picker.
    expect(within(filters).queryByLabelText('total_amount')).not.toBeInTheDocument();
  });

  it('re-resolves the dashboard when a filter is chosen', async () => {
    const filtered = { ...DATA, filtered_row_count: 2600 };
    let calls = 0;
    mockApi(
      detailHandlers({
        [`POST /dashboards/${DASHBOARD_ID}/refresh`]: () => {
          calls += 1;
          return { body: calls > 1 ? filtered : DATA };
        },
      }),
    );

    renderApp(DETAIL_PATH);
    await screen.findByTestId('dashboard-grid');

    await userEvent.selectOptions(screen.getByLabelText('region'), 'North');

    await waitFor(() =>
      expect(screen.getByTestId('dashboard-source').textContent).toMatch(/2[,]?600 rows/),
    );
  });

  it('shows editing controls only in edit mode', async () => {
    mockApi(detailHandlers());

    renderApp(DETAIL_PATH);
    await screen.findByTestId('dashboard-grid');

    // View mode is clean: no add, remove or resize affordances.
    expect(screen.queryByRole('button', { name: 'Add widget' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Remove' })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Edit dashboard' }));

    expect(screen.getByRole('button', { name: 'Add widget' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Remove' }).length).toBeGreaterThan(0);
    expect(screen.getByLabelText('Width of Total revenue')).toBeInTheDocument();
  });

  it('builds a widget from the dataset columns', async () => {
    mockApi(
      detailHandlers({
        [`POST /dashboards/${DASHBOARD_ID}/widgets`]: {
          status: 201,
          body: { id: 'w-new', dashboard_id: DASHBOARD_ID },
        },
      }),
    );

    renderApp(DETAIL_PATH);
    await screen.findByTestId('dashboard-grid');
    await userEvent.click(screen.getByRole('button', { name: 'Edit dashboard' }));
    await userEvent.click(screen.getByRole('button', { name: 'Add widget' }));

    const dialog = await screen.findByTestId('add-widget-dialog');
    // The value column list comes from the dataset's numeric fields.
    const valueColumn = within(dialog).getByLabelText('Value column');
    expect(within(valueColumn).getByRole('option', { name: 'total_amount' })).toBeInTheDocument();

    await userEvent.click(within(dialog).getByRole('button', { name: 'Add widget' }));

    await waitFor(() =>
      expect(screen.queryByTestId('add-widget-dialog')).not.toBeInTheDocument(),
    );
  });

  it('shows an empty state when the dashboard has no widgets', async () => {
    mockApi(
      detailHandlers({
        [`POST /dashboards/${DASHBOARD_ID}/refresh`]: { body: { ...DATA, widgets: [] } },
      }),
    );

    renderApp(DETAIL_PATH);

    expect(await screen.findByTestId('empty-dashboard')).toHaveTextContent(
      'Your dashboard is empty.',
    );
    expect(
      screen.getByRole('button', { name: 'Add your first widget' }),
    ).toBeInTheDocument();
  });

  it('exports through the existing report engine', async () => {
    mockApi(
      detailHandlers({
        [`POST /dashboards/${DASHBOARD_ID}/export`]: {
          status: 201,
          body: {
            id: 'r-1',
            name: 'Sales performance (dashboard)',
            status: 'ready',
            file_format: 'pdf',
            error_message: null,
          },
        },
      }),
    );

    renderApp(DETAIL_PATH);
    await screen.findByTestId('dashboard-grid');

    await userEvent.click(screen.getByRole('button', { name: 'Export PDF' }));

    expect(await screen.findByTestId('dashboard-notice')).toHaveTextContent(
      'report history',
    );
  });
});
