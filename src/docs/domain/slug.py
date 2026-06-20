from __future__ import annotations

import re

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class InvalidSlugError(ValueError):
    pass


def validate_slug(doc_id: str) -> None:
    if not _SLUG_RE.match(doc_id):
        raise InvalidSlugError(
            f"Invalid id: `{doc_id}`. Use lowercase letters, digits, and hyphens (e.g. `my-project`)."
        )
