/**
 * Shared name/slug/description form.
 *
 * Workspaces and projects have the same editable shape, so both their create
 * and edit screens use this one component.
 */

import { useState, type FormEvent } from 'react';

import { ErrorState, FormField, SuccessMessage, TextAreaField } from '@/components/ui';
import {
  toResourcePayload,
  validateResourceForm,
  type FieldErrors,
  type ResourceFormValues,
} from '@/lib/validation';

export interface ResourcePayload {
  name: string;
  slug?: string;
  description?: string;
}

interface ResourceFormProps {
  /** Distinguishes ids when two forms appear on one screen. */
  idPrefix: string;
  initialValues?: Partial<ResourceFormValues>;
  submitLabel: string;
  busyLabel?: string;
  successMessage?: string | null;
  error?: Error | null;
  slugHint?: string;
  onSubmit: (payload: ResourcePayload) => Promise<void>;
  onCancel?: () => void;
  /** Clear the fields after a successful submit (create forms). */
  resetOnSuccess?: boolean;
}

const EMPTY: ResourceFormValues = { name: '', slug: '', description: '' };

export function ResourceForm({
  idPrefix,
  initialValues,
  submitLabel,
  busyLabel = 'Saving…',
  successMessage,
  error,
  slugHint = 'Optional — generated from the name when left blank.',
  onSubmit,
  onCancel,
  resetOnSuccess = false,
}: ResourceFormProps) {
  const [values, setValues] = useState<ResourceFormValues>({ ...EMPTY, ...initialValues });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [submitting, setSubmitting] = useState(false);

  function update(field: keyof ResourceFormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    // Clear the message for a field as soon as the user edits it.
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const errors = validateResourceForm(values);
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }

    setSubmitting(true);
    try {
      await onSubmit(toResourcePayload(values));
      // Keep the values on failure so the user can correct and resubmit.
      if (resetOnSuccess) setValues(EMPTY);
    } catch {
      // The caller stores the failure and renders it through the `error` prop.
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="stack" noValidate>
      <FormField
        id={`${idPrefix}-name`}
        label="Name"
        required
        value={values.name}
        onChange={(event) => update('name', event.target.value)}
        aria-invalid={fieldErrors.name ? true : undefined}
      />
      {fieldErrors.name && (
        <p className="field__error" role="alert">
          {fieldErrors.name}
        </p>
      )}

      <FormField
        id={`${idPrefix}-slug`}
        label="Slug"
        hint={slugHint}
        value={values.slug}
        onChange={(event) => update('slug', event.target.value)}
        aria-invalid={fieldErrors.slug ? true : undefined}
      />
      {fieldErrors.slug && (
        <p className="field__error" role="alert">
          {fieldErrors.slug}
        </p>
      )}

      <TextAreaField
        id={`${idPrefix}-description`}
        label="Description"
        hint="Optional"
        value={values.description}
        onChange={(event) => update('description', event.target.value)}
      />
      {fieldErrors.description && (
        <p className="field__error" role="alert">
          {fieldErrors.description}
        </p>
      )}

      {error && <ErrorState error={error} />}
      {successMessage && <SuccessMessage message={successMessage} />}

      <div className="form__actions">
        <button type="submit" className="button" disabled={submitting}>
          {submitting ? busyLabel : submitLabel}
        </button>
        {onCancel && (
          <button
            type="button"
            className="button button--ghost"
            onClick={onCancel}
            disabled={submitting}
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
