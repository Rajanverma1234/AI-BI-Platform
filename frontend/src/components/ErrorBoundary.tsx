/** Top-level error boundary - keeps a render crash from blanking the app. */

import { Component, type ErrorInfo, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: (error: Error, reset: () => void) => ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Replaced by a real reporting sink (e.g. Sentry) in a later task.
    console.error('Unhandled UI error:', error, info.componentStack);
  }

  private reset = (): void => this.setState({ error: null });

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    if (this.props.fallback) return this.props.fallback(error, this.reset);

    return (
      <div className="panel panel--error" role="alert">
        <h2>Something went wrong</h2>
        <p className="muted">{error.message}</p>
        <button type="button" className="button" onClick={this.reset}>
          Try again
        </button>
      </div>
    );
  }
}
