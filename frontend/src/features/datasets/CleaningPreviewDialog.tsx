import { ErrorState } from '@/components/ui';
import { formatCount } from '@/lib/formatBytes';
import type { CleaningPreviewResponse } from '@/types/api';

interface CleaningPreviewDialogProps {
  preview: CleaningPreviewResponse;
  busy: boolean;
  error: Error | null;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Before/after comparison the user must confirm before anything is written. */
export function CleaningPreviewDialog({
  preview,
  busy,
  error,
  onConfirm,
  onCancel,
}: CleaningPreviewDialogProps) {
  return (
    <div className="modal__backdrop">
      <div
        className="modal modal--wide panel"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="preview-title"
      >
        <h2 id="preview-title">Review cleaning</h2>
        <p className="muted small">
          Nothing has been changed yet. Applying creates a new cleaned version — your original
          dataset is kept as-is.
        </p>

        <div className="table-scroll">
          <table className="table" data-testid="preview-comparison">
            <thead>
              <tr>
                <th scope="col">Measure</th>
                <th scope="col">Before</th>
                <th scope="col">After</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Rows</td>
                <td>{formatCount(preview.original_row_count)}</td>
                <td>{formatCount(preview.cleaned_row_count)}</td>
              </tr>
              <tr>
                <td>Columns</td>
                <td>{formatCount(preview.original_column_count)}</td>
                <td>{formatCount(preview.cleaned_column_count)}</td>
              </tr>
              <tr>
                <td>Missing values</td>
                <td>{formatCount(preview.missing_cells_before)}</td>
                <td>{formatCount(preview.missing_cells_after)}</td>
              </tr>
              <tr>
                <td>Duplicate rows</td>
                <td>{formatCount(preview.duplicate_rows_before)}</td>
                <td>{formatCount(preview.duplicate_rows_after)}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <p className="muted small">
          {formatCount(preview.rows_removed)} row(s) removed ·{' '}
          {preview.affected_columns.length} column(s) affected
          {preview.affected_columns.length > 0 && `: ${preview.affected_columns.join(', ')}`}
        </p>

        {preview.type_changes.length > 0 && (
          <p className="muted small" data-testid="preview-type-changes">
            Type changes:{' '}
            {preview.type_changes
              .map((change) => `${change.column} (${change.before} → ${change.after})`)
              .join(', ')}
          </p>
        )}

        {preview.warnings.length > 0 && (
          <ul className="list" data-testid="preview-warnings">
            {preview.warnings.map((warning) => (
              <li key={warning} className="field__error">
                {warning}
              </li>
            ))}
          </ul>
        )}

        {error && <ErrorState error={error} />}

        <div className="modal__actions">
          <button type="button" className="button button--ghost" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="button" onClick={onConfirm} disabled={busy}>
            {busy ? 'Applying…' : 'Apply cleaning'}
          </button>
        </div>
      </div>
    </div>
  );
}
