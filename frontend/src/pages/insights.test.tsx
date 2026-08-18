import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { clearAuthToken, setAuthToken } from '@/lib/authToken';
import {
  authenticatedHandlers,
  type Handlers,
  mockApi,
  page,
  TEST_PROJECT,
} from '@/test/mockApi';
import { renderApp } from '@/test/renderWithProviders';
import type { BusinessInsight, InsightReport, InsightRunDetail } from '@/types/api';

const DATASET_ID = '66666666-6666-4666-8666-666666666666';
const BASE = `/projects/${TEST_PROJECT.id}/datasets/${DATASET_ID}`;
const INSIGHTS_PATH = `${BASE}/insights`;

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

const REVENUE_RISK: BusinessInsight = {
  id: 'performance-total_amount-down',
  category: 'risk',
  title: 'total_amount is down 14.2%',
  summary:
    'Potential risk detected: total_amount fell -14.2% from 2024-01 to 2024-12. ' +
    'The cause is not established by this data alone.',
  severity: 'high',
  priority: 'critical',
  metric: 'total_amount',
  metric_value: 84000,
  comparison_value: 97900,
  percentage_change: -14.2,
  dimension: 'total_amount',
  dimension_value: null,
  why: 'A falling headline measure compounds if it is not addressed.',
  action: 'Investigate what changed around 2024-12 before the trend continues.',
  evidence: [
    { label: 'total_amount (2024-12)', value: 84000, formatted: '84,000', detail: null },
    { label: 'total_amount (2024-01)', value: 97900, formatted: '97,900', detail: null },
    { label: 'Change', value: -14.2, formatted: '-14.20%', detail: null },
  ],
  confidence: null,
  affected_records: null,
  recommendation: 'Investigate what changed around 2024-12 before the trend continues.',
  source: 'trend analysis',
  priority_score: 72.1,
  priority_reason: 'severity high (+38); magnitude 14.2% (+7); sustained over 12 periods (+10)',
  created_at: '2026-08-14T10:00:00Z',
};

const REGION_OPPORTUNITY: BusinessInsight = {
  ...REVENUE_RISK,
  id: 'region-leader',
  category: 'opportunity',
  title: "'North' is the strongest region",
  summary: "'North' leads region with 41,000 in total_amount, 38.2% of the total.",
  severity: 'info',
  priority: 'low',
  percentage_change: null,
  dimension: 'region',
  dimension_value: 'North',
  why: 'The strongest region is where investment has already converted.',
  action: "Consider whether 'North' has room to expand.",
  evidence: [{ label: 'Top region', value: null, formatted: 'North', detail: null }],
  priority_score: 12.0,
};

/** A risk that is not top-priority, so it lands in Risks rather than Critical. */
const CHURN_RISK: BusinessInsight = {
  ...REVENUE_RISK,
  id: 'customer-churn',
  category: 'risk',
  title: '24.0% of customers have gone inactive',
  summary: 'Potential risk detected: 24.0% of customers have no activity for 90+ days.',
  severity: 'medium',
  priority: 'medium',
  metric: 'churn_rate',
  percentage_change: null,
  dimension: 'customer_id',
  dimension_value: null,
  priority_score: 34.0,
};

const REPORT: InsightReport = {
  run_id: '77777777-7777-4777-8777-777777777777',
  project_id: TEST_PROJECT.id,
  dataset_id: DATASET_ID,
  dataset_name: 'Sales export',
  version_id: null,
  version_label: 'Original dataset',
  analysis_version: '1',
  generated_at: '2026-08-14T10:00:00Z',
  generated_by: 'Owner',
  row_count: 5000,
  column_count: 12,
  summary: 'This dataset covers 5,000 records across 12 columns.',
  health: {
    score: 42,
    rating: 'at_risk',
    methodology:
      'Each signal below is scored 0-100 from measured figures, then combined as a ' +
      'weighted average.',
    factors: [
      {
        key: 'revenue_trend',
        name: 'Revenue trend',
        status: 'negative',
        score: 35,
        weight: 0.6,
        detail: 'total_amount is decreasing - -14.2% across 12 month periods.',
        evidence: [{ label: 'Change', value: -14.2, formatted: '-14.20%', detail: null }],
      },
    ],
    excluded: [
      { factor: 'Rating trend', reason: 'Rating trend needs a rating column. Not provided.' },
    ],
  },
  insights: [REVENUE_RISK, CHURN_RISK, REGION_OPPORTUNITY],
  recommendations: [
    {
      id: 'rec-performance-total_amount-down',
      title: 'total_amount is down 14.2%',
      action: 'Investigate what changed around 2024-12 before the trend continues.',
      reason: 'Potential risk detected: total_amount fell -14.2%.',
      supporting_insight_ids: [REVENUE_RISK.id],
      expected_impact: 'Potential impact: avoiding further loss if the trend continues.',
      priority: 'critical',
      category: 'risk',
      source: 'deterministic',
    },
  ],
  supporting_metrics: [
    { label: 'Total total_amount', value: 1084000, formatted: '1,084,000', detail: null },
  ],
  filters: {
    categories: ['risk', 'opportunity'],
    severities: ['high', 'medium', 'info'],
    priorities: ['critical', 'medium', 'low'],
    products: ['Electronics', 'Grocery'],
    regions: ['North', 'South'],
    customer_segments: [],
    periods: ['2024-01', '2024-12'],
    product_column: 'category',
    region_column: 'region',
    date_column: 'order_date',
  },
  counts_by_category: { risk: 2, opportunity: 1 },
  counts_by_severity: { high: 1, medium: 1, info: 1 },
  counts_by_priority: { critical: 1, medium: 1, low: 1 },
  ai_available: false,
  ai_status: 'AI interpretation unavailable: the provider is not configured.',
  ai: null,
  skipped: [{ analysis: 'seasonality', reason: 'Seasonal patterns need at least 24 months.' }],
  stale: false,
};

const RUN_DETAIL: InsightRunDetail = {
  run: {
    id: REPORT.run_id!,
    project_id: TEST_PROJECT.id,
    dataset_id: DATASET_ID,
    dataset_version_id: null,
    analysis_version: '1',
    status: 'ready',
    health_score: 42,
    health_rating: 'at_risk',
    insight_count: 3,
    recommendation_count: 1,
    ai_available: false,
    ai_status: null,
    error_message: null,
    created_at: '2026-08-14T10:00:00Z',
    updated_at: '2026-08-14T10:00:00Z',
  },
  report: REPORT,
};

function handlers(extra: Handlers = {}): Handlers {
  return authenticatedHandlers({
    [`GET ${BASE}`]: { body: DATASET },
    [`GET ${BASE}/versions`]: { body: page([]) },
    [`GET ${INSIGHTS_PATH}/latest`]: { body: null },
    ...extra,
  });
}

describe('DatasetInsightsPage', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    clearAuthToken();
    setAuthToken('a-valid-access-token');
  });

  it('invites the user to generate insights when none exist', async () => {
    mockApi(handlers());

    renderApp(INSIGHTS_PATH);

    expect(await screen.findByTestId('no-insights')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Generate insights' })).toBeInTheDocument();
  });

  it('shows a stored run without regenerating it', async () => {
    mockApi(handlers({ [`GET ${INSIGHTS_PATH}/latest`]: { body: RUN_DETAIL } }));

    renderApp(INSIGHTS_PATH);

    expect(await screen.findByTestId('business-health')).toHaveTextContent('42/100');
    expect(screen.getByTestId('group-critical')).toHaveTextContent('total_amount is down 14.2%');
  });

it('places each finding in exactly one group', async () => {
    mockApi(handlers({ [`POST ${INSIGHTS_PATH}`]: { status: 201, body: REPORT } }));

    renderApp(INSIGHTS_PATH);
    await userEvent.click(await screen.findByRole('button', { name: 'Generate insights' }));

    // The top-priority risk is an alert, not a third copy under Risks.
    const critical = await screen.findByTestId('group-critical');
    expect(critical).toHaveTextContent('total_amount is down');
    expect(screen.getByTestId('group-risks')).toHaveTextContent('gone inactive');
    expect(screen.getByTestId('group-risks')).not.toHaveTextContent('total_amount is down');
    expect(screen.getByTestId('group-opportunities')).toHaveTextContent(
      "'North' is the strongest region",
    );
    // One card per finding, never a duplicate across groups.
    expect(screen.getAllByTestId(`insight-${REVENUE_RISK.id}`)).toHaveLength(1);
  });

  it('explains why a finding is shown, with its evidence', async () => {
    mockApi(handlers({ [`GET ${INSIGHTS_PATH}/latest`]: { body: RUN_DETAIL } }));

    renderApp(INSIGHTS_PATH);

    const card = await screen.findByTestId(`insight-${REVENUE_RISK.id}`);
    await userEvent.click(
      within(card).getByRole('button', { name: 'Why am I seeing this?' }),
    );

    const evidence = screen.getByTestId(`evidence-${REVENUE_RISK.id}`);
    expect(evidence).toHaveTextContent('total_amount (2024-12)');
    expect(evidence).toHaveTextContent('84,000');
    // The ranking is shown too, so the ordering is never a black box.
    expect(evidence).toHaveTextContent('severity high (+38)');
  });

  it('shows how the health score is calculated on request', async () => {
    mockApi(handlers({ [`GET ${INSIGHTS_PATH}/latest`]: { body: RUN_DETAIL } }));

    renderApp(INSIGHTS_PATH);
    await userEvent.click(
      await screen.findByRole('button', { name: 'How is this calculated?' }),
    );

    expect(screen.getByTestId('health-methodology')).toHaveTextContent('weighted average');
    expect(screen.getByTestId('health-factors')).toHaveTextContent('Revenue trend');
    // Signals that could not be measured are named, not hidden.
    expect(screen.getByTestId('health-excluded')).toHaveTextContent('Rating trend');
  });

  it('states that insights are deterministic when no AI provider is configured', async () => {
    mockApi(handlers({ [`GET ${INSIGHTS_PATH}/latest`]: { body: RUN_DETAIL } }));

    renderApp(INSIGHTS_PATH);

    expect(await screen.findByTestId('ai-status')).toHaveTextContent(
      'AI interpretation unavailable. Showing data-driven insights.',
    );
  });

  it('filters findings using values taken from the dataset', async () => {
    mockApi(handlers({ [`GET ${INSIGHTS_PATH}/latest`]: { body: RUN_DETAIL } }));

    renderApp(INSIGHTS_PATH);

    const filters = await screen.findByTestId('insight-filters');
    // The region filter is labelled with the dataset's own column name.
    await userEvent.selectOptions(within(filters).getByLabelText('region'), 'South');

    // The North opportunity is about a different region, so it drops out.
    expect(screen.queryByTestId('group-opportunities')).not.toBeInTheDocument();
    // The dataset-wide findings are not about a region, so they stay.
    expect(screen.getByTestId('group-critical')).toBeInTheDocument();
    expect(screen.getByTestId('group-risks')).toBeInTheDocument();
  });

  it('lists analyses that could not run, with reasons', async () => {
    mockApi(handlers({ [`GET ${INSIGHTS_PATH}/latest`]: { body: RUN_DETAIL } }));

    renderApp(INSIGHTS_PATH);

    expect(await screen.findByTestId('insights-skipped')).toHaveTextContent(
      'Seasonal patterns need at least 24 months.',
    );
  });

  it('warns when a stored run no longer matches what is being viewed', async () => {
    mockApi(
      handlers({
        [`GET ${INSIGHTS_PATH}/latest`]: {
          body: { ...RUN_DETAIL, report: { ...REPORT, stale: true } },
        },
      }),
    );

    renderApp(INSIGHTS_PATH);

    expect(await screen.findByTestId('stale-notice')).toHaveTextContent('Refresh');
  });

  it('shows recommendations without promising an outcome', async () => {
    mockApi(handlers({ [`GET ${INSIGHTS_PATH}/latest`]: { body: RUN_DETAIL } }));

    renderApp(INSIGHTS_PATH);

    const recommendations = await screen.findByTestId('recommendations');
    expect(recommendations).toHaveTextContent('Potential impact');
    expect(recommendations).not.toHaveTextContent('will increase');
  });
});
