import { useEffect, useRef } from 'react';

import { ErrorState } from '@/components/ui/ErrorState';

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  /** Shown when the destructive action itself fails. */
  error?: Error | null;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Blocking confirmation for destructive actions.
 *
 * Focus moves to the cancel button on open, so the safe choice is the default
 * and Escape always backs out.
 */
export function ConfirmDialog({
  title,
  message,
  confirmLabel = 'Delete',
  error,
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onCancel();
    }
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [onCancel]);

  return (
    <div className="modal__backdrop">
      <div
        className="modal panel"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-message"
      >
        <h2 id="confirm-title">{title}</h2>
        <p id="confirm-message" className="muted">
          {message}
        </p>

        {error && <ErrorState error={error} />}

        <div className="modal__actions">
          <button
            type="button"
            className="button button--ghost"
            onClick={onCancel}
            ref={cancelRef}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            className="button button--danger"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Deleting…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
