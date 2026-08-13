"""Shared pagination query parameters.

Declared once so every list endpoint exposes the same contract in OpenAPI and
services receive an already-validated page request.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query

from app.core.pagination import Pagination
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def pagination_params(
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=MAX_PAGE_SIZE, description=f"Items per page (max {MAX_PAGE_SIZE})"),
    ] = DEFAULT_PAGE_SIZE,
) -> Pagination:
    return Pagination(page=page, page_size=page_size)


#: Attach to any list route: `pagination: PageParams`.
PageParams = Annotated[Pagination, Depends(pagination_params)]

__all__ = ["PageParams", "Pagination", "pagination_params"]
