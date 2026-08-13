import type { DatasetStatus } from '@/types/api';

interface DatasetStatusBadgeProps {
  status: DatasetStatus;
}

const LABELS: Record<DatasetStatus, string> = {
  uploading: 'Uploading',
  processing: 'Processing',
  ready: 'Ready',
  failed: 'Failed',
};

/** Maps the four processing states onto the existing badge styles. */
const TONE: Record<DatasetStatus, string> = {
  uploading: 'degraded',
  processing: 'degraded',
  ready: 'ok',
  failed: 'error',
};

export function DatasetStatusBadge({ status }: DatasetStatusBadgeProps) {
  return (
    <span className={`badge badge--${TONE[status]}`} data-testid="dataset-status">
      {LABELS[status]}
    </span>
  );
}
