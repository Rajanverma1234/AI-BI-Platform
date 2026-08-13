"""Small, dependency-free helpers."""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, max_length: int = 100) -> str:
    """Convert arbitrary text into a URL-safe slug.

    Used for workspace and project slugs.
    """
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = _NON_ALNUM.sub("-", normalized.lower()).strip("-")
    return slug[:max_length].rstrip("-")
