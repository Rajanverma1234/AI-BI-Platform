"""Small, dependency-free helpers."""

from __future__ import annotations

import re
import unicodedata

from app.core.exceptions import ValidationError

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, max_length: int = 100) -> str:
    """Convert arbitrary text into a URL-safe slug.

    Used for workspace and project slugs.
    """
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = _NON_ALNUM.sub("-", normalized.lower()).strip("-")
    return slug[:max_length].rstrip("-")


def resolve_slug(explicit: str | None, name: str) -> str:
    """Use a caller-supplied slug, else derive one from ``name``.

    Shared by workspaces and projects, which follow the same rule.
    """
    slug = explicit or slugify(name)
    if not slug:
        raise ValidationError("Could not derive a slug from the name; provide one explicitly.")
    return slug
