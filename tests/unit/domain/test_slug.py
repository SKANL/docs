import pytest
from docs.domain.slug import validate_slug, InvalidSlugError


@pytest.mark.parametrize("good", ["a", "mi-proyecto", "doc1", "2026-tesis"])
def test_accepts_valid_slugs(good):
    validate_slug(good)  # does not raise


@pytest.mark.parametrize("bad", ["", "-leading", "UPPER", "with space", "under_score", "accént"])
def test_rejects_invalid_slugs(bad):
    with pytest.raises(InvalidSlugError):
        validate_slug(bad)
