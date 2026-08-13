interface SuccessMessageProps {
  message: string;
}

/** Inline confirmation after a successful write. Announced to screen readers. */
export function SuccessMessage({ message }: SuccessMessageProps) {
  return (
    <p className="notice notice--success" role="status" data-testid="success-message">
      {message}
    </p>
  );
}
