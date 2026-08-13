import { Link } from 'react-router-dom';

export default function NotFoundPage() {
  return (
    <div className="stack">
      <h1>Page not found</h1>
      <p className="muted">That route does not exist.</p>
      <Link className="button" to="/">
        Back to overview
      </Link>
    </div>
  );
}
