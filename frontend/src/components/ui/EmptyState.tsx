import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  hint?: string;
  action?: ReactNode;
  testId?: string;
}

/** Shown when a list loaded successfully but has nothing in it. */
export function EmptyState({ title, hint, action, testId }: EmptyStateProps) {
  return (
    <div className="empty" data-testid={testId}>
      <p className="empty__title">{title}</p>
      {hint && <p className="muted small">{hint}</p>}
      {action}
    </div>
  );
}
