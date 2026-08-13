import { ApiError } from '@/lib/apiClient';

interface ErrorStateProps {
  error: Error;
  onRetry?: () => void;
}

/** Shared presentation for a failed request. */
export function ErrorState({ error, onRetry }: ErrorStateProps) {
  const isApiError = error instanceof ApiError;

  return (
    <div className="panel panel--error" role="alert">
      <h3>Request failed</h3>
      <p className="muted">{error.message}</p>
      {isApiError && !error.isNetworkError && (
        <p className="muted small">
          code: {error.code}
          {error.status ? ` · status: ${error.status}` : ''}
          {error.requestId ? ` · request: ${error.requestId}` : ''}
        </p>
      )}
      {onRetry && (
        <button type="button" className="button" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
