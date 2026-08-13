import { useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '@/auth/useAuth';
import { Card, ErrorState, FormField } from '@/components/ui';

interface LocationState {
  from?: string;
}

export default function LoginPage() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<Error | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login({ email, password });
      // Return the user to whatever they were trying to reach.
      const { from } = (location.state ?? {}) as LocationState;
      navigate(from ?? '/', { replace: true });
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="stack stack--narrow">
      <div>
        <h1>Sign in</h1>
        <p className="muted">Access your workspaces and projects.</p>
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
            id="password"
            label="Password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />

          {error && <ErrorState error={error} />}

          <button type="submit" className="button" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </Card>

      <p className="muted small">
        No account yet? <Link to="/register">Create one</Link>
      </p>
    </div>
  );
}
