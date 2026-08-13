import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { BackendStatus } from '@/features/health/BackendStatus';
import { mockJsonFetch, mockNetworkFailure } from '@/test/mockFetch';

const HEALTH_PAYLOAD = {
  status: 'ok',
  service: 'AI BI Platform',
  version: '0.1.0',
  environment: 'development',
};

describe('BackendStatus', () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
  });

  it('shows a loading state before the response arrives', () => {
    mockJsonFetch(HEALTH_PAYLOAD);

    render(<BackendStatus />);

    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('renders the backend identity once connected', async () => {
    mockJsonFetch(HEALTH_PAYLOAD);

    render(<BackendStatus />);

    expect(await screen.findByTestId('health-result')).toBeInTheDocument();
    expect(screen.getByTestId('status-badge')).toHaveTextContent('Healthy');
    expect(screen.getByText('AI BI Platform')).toBeInTheDocument();
    expect(screen.getByText('0.1.0')).toBeInTheDocument();
  });

  it('renders an actionable error when the backend is unreachable', async () => {
    mockNetworkFailure();

    render(<BackendStatus />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not reach the API/);
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('recovers when the backend comes back and the user retries', async () => {
    mockNetworkFailure();
    render(<BackendStatus />);
    await screen.findByRole('alert');

    mockJsonFetch(HEALTH_PAYLOAD);
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(screen.getByTestId('health-result')).toBeInTheDocument());
  });
});
