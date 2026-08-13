import type { TextareaHTMLAttributes } from 'react';

interface TextAreaFieldProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label: string;
  id: string;
  hint?: string;
}

/** Multi-line counterpart to FormField, used for descriptions. */
export function TextAreaField({ label, id, hint, ...textAreaProps }: TextAreaFieldProps) {
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea id={id} className="input" rows={3} {...textAreaProps} />
      {hint && <span className="muted small">{hint}</span>}
    </div>
  );
}
