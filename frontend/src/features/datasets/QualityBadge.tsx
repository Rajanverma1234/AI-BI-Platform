import type { QualitySeverity, QualityStatus } from '@/types/api';

const STATUS_TONE: Record<QualityStatus, string> = {
  good: 'ok',
  warning: 'degraded',
  critical: 'error',
};

const STATUS_LABEL: Record<QualityStatus, string> = {
  good: 'Good',
  warning: 'Warning',
  critical: 'Critical',
};

export function QualityBadge({ status }: { status: QualityStatus }) {
  return (
    <span className={`badge badge--${STATUS_TONE[status]}`} data-testid="quality-status">
      {STATUS_LABEL[status]}
    </span>
  );
}

const SEVERITY_TONE: Record<QualitySeverity, string> = {
  info: 'degraded',
  warning: 'degraded',
  critical: 'error',
};

export function SeverityBadge({ severity }: { severity: QualitySeverity }) {
  return <span className={`badge badge--${SEVERITY_TONE[severity]}`}>{severity}</span>;
}
