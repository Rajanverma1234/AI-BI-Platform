import type { InputHTMLAttributes } from 'react';

interface FormFieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  id: string;
  hint?: string;
}

/** Labelled input; the label is bound to the control for accessibility. */
export function FormField({ label, id, hint, ...inputProps }: FormFieldProps) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input id={id} className="input" {...inputProps} />
      {hint && <span className="muted small">{hint}</span>}
    </div>
  );
}
