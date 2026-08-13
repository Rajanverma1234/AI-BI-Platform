import { useState, type FormEvent } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { useAuth } from '@/auth/useAuth';
import { Card, ErrorState, FormField } from '@/components/ui';

/** Mirrors the backend minimum so the user is told before the round trip. */
const PASSWORD_MIN_LENGTH = 8;

export default function RegisterPage() {
  const { register } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (password.length < PASSWORD_MIN_LENGTH) {
      setError(new Error(`Password must be at least ${PASSWORD_MIN_LENGTH} characters.`));
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      await register({
        email,
        password,
        ...(displayName.trim() ? { display_name: displayName.trim() } : {}),
      });
      // register() signs the user in, so go straight into the app.
      navigate('/', { replace: true });
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="stack stack--narrow">
      <div>
        <h1>Create an account</h1>
        <p className="muted">Set up your first workspace in a minute.</p>
      </div>

      <Card>
        <form onSubmit={handleSubmit} className="stack" noValidate>
          <FormField
            id="email"
            label="Email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <FormField
            id="displayName"
            label="Display name"
            hint="Optional"
            autoComplete="name"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
          />
          <FormField
            id="password"
            label="Password"
            type="password"
            autoComplete="new-password"
            required
            minLength={PASSWORD_MIN_LENGTH}
            hint={`At least ${PASSWORD_MIN_LENGTH} characters`}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />

          {error && <ErrorState error={error} />}

          <button type="submit" className="button" disabled={submitting}>
            {submitting ? 'Creating account…' : 'Create account'}
          </button>
        </form>
      </Card>

      <p className="muted small">
        Already registered? <Link to="/login">Sign in</Link>
      </p>
    </div>
  );
}
