interface PaginationProps {
  page: number;
  totalPages: number;
  total: number;
  hasNext: boolean;
  hasPrevious: boolean;
  onPageChange: (page: number) => void;
}

/** Previous/next control; renders nothing while everything fits on one page. */
export function Pagination({
  page,
  totalPages,
  total,
  hasNext,
  hasPrevious,
  onPageChange,
}: PaginationProps) {
  if (totalPages <= 1) return null;

  return (
    <nav className="pagination" aria-label="Pagination">
      <button
        type="button"
        className="button button--ghost"
        onClick={() => onPageChange(page - 1)}
        disabled={!hasPrevious}
      >
        Previous
      </button>
      <span className="muted small" data-testid="pagination-status">
        Page {page} of {totalPages} · {total} total
      </span>
      <button
        type="button"
        className="button button--ghost"
        onClick={() => onPageChange(page + 1)}
        disabled={!hasNext}
      >
        Next
      </button>
    </nav>
  );
}
