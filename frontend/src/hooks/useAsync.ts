/**
 * Foundation for loading/error state.
 *
 * Wraps a promise-returning function in the four states every data-driven
 * screen needs, and cancels in-flight requests on unmount or re-run.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

export type AsyncStatus = 'idle' | 'loading' | 'success' | 'error';

export interface AsyncState<T> {
  status: AsyncStatus;
  data: T | null;
  error: Error | null;
  isLoading: boolean;
  /** Re-run the request; safe to call from an event handler. */
  reload: () => void;
}

export function useAsync<T>(
  fn: (signal: AbortSignal) => Promise<T>,
  options: { immediate?: boolean } = {},
): AsyncState<T> {
  const { immediate = true } = options;
  const [status, setStatus] = useState<AsyncStatus>(immediate ? 'loading' : 'idle');
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [runId, setRunId] = useState(immediate ? 1 : 0);

  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (runId === 0) return;

    const controller = new AbortController();
    let active = true;
    setStatus('loading');
    setError(null);

    fnRef
      .current(controller.signal)
      .then((result) => {
        if (!active) return;
        setData(result);
        setStatus('success');
      })
      .catch((cause: unknown) => {
        if (!active || controller.signal.aborted) return;
        setError(cause instanceof Error ? cause : new Error(String(cause)));
        setStatus('error');
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, [runId]);

  const reload = useCallback(() => setRunId((id) => id + 1), []);

  return { status, data, error, isLoading: status === 'loading', reload };
}
