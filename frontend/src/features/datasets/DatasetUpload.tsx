/**
 * Drag-and-drop plus file-picker upload area.
 *
 * Extension checks happen here purely for fast feedback; the backend performs
 * the authoritative validation of type, size and contents.
 */

import { useRef, useState, type DragEvent } from 'react';

import { ErrorState, SuccessMessage } from '@/components/ui';

export const ACCEPTED_EXTENSIONS = ['csv', 'xlsx'] as const;
const ACCEPT_ATTRIBUTE = '.csv,.xlsx';

interface DatasetUploadProps {
  onUpload: (file: File) => Promise<void>;
  busy: boolean;
  progress: number | null;
  error: Error | null;
  successMessage: string | null;
  label?: string;
}

function hasAcceptedExtension(file: File): boolean {
  const extension = file.name.split('.').pop()?.toLowerCase() ?? '';
  return (ACCEPTED_EXTENSIONS as readonly string[]).includes(extension);
}

export function DatasetUpload({
  onUpload,
  busy,
  progress,
  error,
  successMessage,
  label = 'Drag a CSV or XLSX file here',
}: DatasetUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    if (!hasAcceptedExtension(file)) {
      setLocalError(`Unsupported file type. Upload one of: ${ACCEPTED_EXTENSIONS.join(', ')}.`);
      return;
    }
    setLocalError(null);
    await onUpload(file);
    // Allow re-selecting the same filename immediately after an upload.
    if (inputRef.current) inputRef.current.value = '';
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (busy) return;
    void handleFile(event.dataTransfer.files?.[0]);
  }

  return (
    <div className="stack">
      <div
        className={`dropzone${dragging ? ' dropzone--active' : ''}${busy ? ' dropzone--busy' : ''}`}
        onDragOver={(event) => {
          event.preventDefault();
          if (!busy) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        data-testid="dataset-dropzone"
      >
        <p className="dropzone__label">{label}</p>
        <p className="muted small">or</p>

        <button
          type="button"
          className="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
        >
          {busy ? 'Uploading…' : 'Choose a file'}
        </button>

        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT_ATTRIBUTE}
          className="visually-hidden"
          aria-label="Dataset file"
          onChange={(event) => void handleFile(event.target.files?.[0])}
          disabled={busy}
        />
      </div>

      {busy && progress !== null && (
        <div className="progress" data-testid="upload-progress">
          <div
            className="progress__bar"
            role="progressbar"
            aria-valuenow={progress}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Upload progress"
            style={{ width: `${progress}%` }}
          />
          <span className="muted small">
            {progress < 100 ? `Uploading ${progress}%` : 'Processing file…'}
          </span>
        </div>
      )}

      {localError && (
        <p className="field__error" role="alert">
          {localError}
        </p>
      )}
      {error && <ErrorState error={error} />}
      {successMessage && <SuccessMessage message={successMessage} />}
    </div>
  );
}
