"""Framework-free pagination primitive.

Lives in ``core`` so services can accept it without importing the API layer;
``app/api/pagination.py`` adapts it to FastAPI query parameters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pagination:
    """A validated 1-based page request."""

    page: int
    page_size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size
