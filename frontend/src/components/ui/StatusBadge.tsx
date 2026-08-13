import type { ServiceStatus } from '@/types/api';

interface StatusBadgeProps {
  status: ServiceStatus;
  label?: string;
}

const LABELS: Record<ServiceStatus, string> = {
  ok: 'Healthy',
  degraded: 'Degraded',
  error: 'Unavailable',
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  return (
    <span className={`badge badge--${status}`} data-testid="status-badge">
      {label ?? LABELS[status]}
    </span>
  );
}
