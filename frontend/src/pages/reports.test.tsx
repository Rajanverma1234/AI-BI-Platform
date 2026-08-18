import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearAuthToken, setAuthToken } from '@/lib/authToken';
import {
  authenticatedHandlers,
  mockApi,
  page,
  TEST_PROJECT,
  type Handlers,
} from '@/test/mockApi';
import { renderApp } from '@/test/renderWithProviders';
import type { Report, ReportData, ReportOptions } from '@/types/api';

const DATASET_ID = '44444444-4444-4444-8444-444444444444';
const BASE = `/projects/${TEST_PROJECT.id}/datasets/${DATASET_ID}`;
const REPORTS_PATH = `${BASE}/reports`;

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

const OPTIONS: ReportOptions = {
  dataset_id: DATASET_ID,
  version_id: null,
  detected_columns: { revenue: 'total_amount', date: 'order_date' },
  formats: ['pdf', 'xlsx', 'csv', 'pptx'],
  templates: [
    {
      template: 'executive',
      name: 'Executive business review',
      description: 'A short board-level read.',
      sections: ['executive_summary', 'kpis'],
      unavailable_sections: ['cohort'],
    },
  ],
  sections: [
    {
      key: 'executive_summary',
      title: 'Executive summary',
      available: true,
      reason: null,
      required_roles: [],
    },
    { key: 'kpis', title: 'Key performance indicators', available: true, reason: null, required_roles: [] },
    {
      key: 'cohort',
      title: 'Cohort retention',
      available: false,
      reason: 'Cohort retention requires a customer/entity identifier and a transaction date.',
      required_roles: ['customer', 'date'],
    },
  ],
};

const PREVIEW: ReportData = {
  title: 'Sales export - Executive business review',
  subtitle: 'A short board-level read.',
  project_id: TEST_PROJECT.id,
  dataset_id: DATASET_ID,
  dataset_name: 'Sales export',
  version_id: null,
  version_label: 'Original dataset',
  template: 'executive',
  generated_at: '2026-08-14T10:00:00Z',
  generated_by: 'Owner',
  row_count: 5000,
  column_count: 12,
  ai_available: false,
  ai_status: 'No AI provider is configured.',
  sections: [
    {
      key: 'executive_summary',
      title: 'Executive summary',
      narrative: ['The dataset holds 5,000 rows across 12 columns.'],
      metrics: [{ label: 'Rows', value: '5,000', detail: null }],
      tables: [],
      bullets: ['Revenue is increasing.'],
      unavailable_reason: null,
    },
    {
      key: 'kpis',
      title: 'Key performance indicators',
      narrative: [],
      metrics: [],
      tables: [
        {
          title: null,
          columns: ['KPI', 'Value'],
          rows: [['Total total_amount', 123456.78]],
          note: 'Showing the first 25 of 40 rows.',
        },
      ],
      bullets: [],
      unavailable_reason: null,
    },
  ],
  skipped: [{ section: 'cohort', reason: 'No customer identifier was detected.' }],
};

const READY_REPORT: Report = {
  id: '55555555-5555-4555-8555-555555555555',
  project_id: TEST_PROJECT.id,
  dataset_id: DATASET_ID,
  dataset_version_id: null,
  name: 'Sales export - Executive business review',
  template: 'executive',
  file_format: 'pdf',
  sections: ['executive_summary', 'kpis'],
  status: 'ready',
  file_size: 51200,
  error_message: null,
  created_at: '2026-08-14T10:00:00Z',
  updated_at: '2026-08-14T10:00:00Z',
};

function handlers(extra: Handlers = {}): Handlers {
  return authenticatedHandlers({
    [`GET ${BASE}`]: { body: DATASET },
    [`GET ${BASE}/versions`]: { body: page([]) },
    [`GET ${REPORTS_PATH}/options`]: { body: OPTIONS },
    [`GET ${REPORTS_PATH}`]: { body: page([]) },
    ...extra,
  });
}

describe('DatasetReportsPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
    setAuthToken('a-valid-access-token');
  });

  it('offers only the sections this dataset supports, and explains the rest', async () => {
    mockApi(handlers());

    renderApp(REPORTS_PATH);

    const sections = await screen.findByTestId('report-sections');
    expect(within(sections).getByLabelText('Executive summary')).toBeInTheDocument();
    // Cohort is impossible here, so it must not be selectable...
    expect(within(sections).queryByLabelText('Cohort retention')).not.toBeInTheDocument();

    // ...but the reason must still be visible rather than silently hidden.
    const blocked = screen.getByTestId('report-blocked-sections');
    expect(blocked).toHaveTextContent('Cohort retention');
    expect(blocked).toHaveTextContent('requires a customer/entity identifier');
  });

  it('previews the same report the export is built from', async () => {
    mockApi(handlers({ [`POST ${REPORTS_PATH}/preview`]: { body: PREVIEW } }));

    renderApp(REPORTS_PATH);

    await userEvent.click(await screen.findByRole('button', { name: 'Preview' }));

    const preview = await screen.findByTestId('report-preview');
    expect(preview).toHaveTextContent('The dataset holds 5,000 rows across 12 columns.');
    expect(within(preview).getByTestId('report-section-kpis')).toHaveTextContent('123,456.78');
    // The truncation note travels with the data, so every format agrees.
    expect(preview).toHaveTextContent('Showing the first 25 of 40 rows.');
  });

  it('states that the report is deterministic when no AI provider is configured', async () => {
    mockApi(handlers({ [`POST ${REPORTS_PATH}/preview`]: { body: PREVIEW } }));

    renderApp(REPORTS_PATH);
    await userEvent.click(await screen.findByRole('button', { name: 'Preview' }));

    expect(await screen.findByTestId('report-ai-status')).toHaveTextContent(
      'No AI provider is configured.',
    );
  });

  it('lists sections that were left out of the report', async () => {
    mockApi(handlers({ [`POST ${REPORTS_PATH}/preview`]: { body: PREVIEW } }));

    renderApp(REPORTS_PATH);
    await userEvent.click(await screen.findByRole('button', { name: 'Preview' }));

    expect(await screen.findByTestId('report-skipped')).toHaveTextContent(
      'No customer identifier was detected.',
    );
  });

  it('confirms a generated report and shows it in the history', async () => {
    let generated = false;
    mockApi(
      handlers({
        [`POST ${REPORTS_PATH}`]: { status: 201, body: READY_REPORT },
        [`GET ${REPORTS_PATH}`]: () => ({
          body: page(generated ? [READY_REPORT] : []),
        }),
      }),
    );

    renderApp(REPORTS_PATH);

    await screen.findByTestId('no-reports');
    generated = true;
    await userEvent.click(screen.getByRole('button', { name: 'Generate PDF' }));

    expect(await screen.findByTestId('report-notice')).toHaveTextContent('is ready to download');
    await waitFor(() => expect(screen.getByTestId('report-history')).toBeInTheDocument());
    expect(screen.getByTestId('report-history')).toHaveTextContent('50.0 KB');
  });

  it('keeps a failed report visible with its reason', async () => {
    mockApi(
      handlers({
        [`GET ${REPORTS_PATH}`]: {
          body: page([
            {
              ...READY_REPORT,
              status: 'failed',
              file_size: 0,
              error_message: 'The PPTX file could not be produced from this report.',
            },
          ]),
        },
      }),
    );

    renderApp(REPORTS_PATH);

    const history = await screen.findByTestId('report-history');
    expect(history).toHaveTextContent('could not be produced');
    // Nothing to download, so no download control is offered.
    expect(within(history).queryByRole('button', { name: 'Download' })).not.toBeInTheDocument();
  });
});
