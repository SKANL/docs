"""Golden bytes for every call site that serialises canonical JSON.

These pin the hashed/stored bytes so folding the variants into
`domain.identity.canonical_json` cannot change any digest.
"""

from pathlib import Path
from types import MappingProxyType

import pytest

from docs.api.openapi import canonical_json as openapi_canonical_json
from docs.domain import identity, provenance
from docs.domain.evidence_passport import canonical_json as passport_canonical_json
from docs.domain.pipeline_kernel import deterministic_json
from docs.domain.pipeline_policy import PipelinePolicy
from docs.plugins.manifest import ManifestError
from docs.plugins.manifest import _canonical as manifest_canonical

SAMPLE = {"z": [3, 1, {"b": None, "a": True}], "é": '世界 "q" \n', "a": 1.5, "n": {"y": 0, "x": -2}}
EXPECTED = '{"a":1.5,"n":{"x":-2,"y":0},"z":[3,1,{"a":true,"b":null}],"é":"世界 \\"q\\" \\n"}'
FROZEN = MappingProxyType({"k": (1, 2, MappingProxyType({"b": 1, "a": 2})), "á": "ü"})


def test_identity_canonical_json_golden() -> None:
    assert identity.canonical_json(SAMPLE) == EXPECTED
    assert identity.canonical_json(SAMPLE, strict=True) == EXPECTED


def test_strict_mode_rejects_what_lenient_mode_stringifies() -> None:
    assert identity.canonical_json({"p": Path("a")}) == '{"p":"a"}'
    with pytest.raises(TypeError):
        identity.canonical_json({"p": Path("a")}, strict=True)
    with pytest.raises(ValueError):
        identity.canonical_json({"n": float("nan")}, strict=True)


def test_every_variant_keeps_its_bytes() -> None:
    assert identity.canonical_json(SAMPLE, strict=True) == EXPECTED
    assert identity.canonical_json(FROZEN, strict=True) == '{"k":[1,2,{"a":2,"b":1}],"á":"ü"}'
    assert provenance._sha256(SAMPLE) == identity.sha256_bytes(EXPECTED.encode("utf-8"))
    assert passport_canonical_json(SAMPLE) == EXPECTED.encode("utf-8")
    assert manifest_canonical(SAMPLE) == EXPECTED.encode("utf-8")
    assert openapi_canonical_json(SAMPLE) == EXPECTED


def test_pipeline_kernel_sorts_sets_and_posixes_paths() -> None:
    assert deterministic_json({"s": {3, 1, 2}, "p": Path("a/b"), "t": (1, "é")}) == (
        '{"p":"a/b","s":[1,2,3],"t":[1,"é"]}'
    )


def test_policy_json_golden() -> None:
    assert PipelinePolicy(warning_codes=("b", "a")).to_json() == '{"mode":"draft","warning_codes":["a","b"]}'


def test_manifest_rejects_non_finite_numbers() -> None:
    with pytest.raises(ManifestError):
        manifest_canonical({"n": float("nan")})
