import re
from pathlib import Path

from docs.application.authoring_clock import authoring_timestamp


def test_authoring_timestamp_uses_the_cli_second_precision_format() -> None:
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", authoring_timestamp())


def test_every_authoring_surface_shares_the_one_clock() -> None:
    import docs.api.section_routes as routes
    import docs.sidecar as sidecar

    assert routes.authoring_timestamp is authoring_timestamp
    assert "authoring_timestamp()" in Path(sidecar.__file__).read_text(encoding="utf-8")
