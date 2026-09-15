from pathlib import Path

from docs.domain.identity import canonical_json, sha256_bytes, sha256_content, sha256_file


def test_identity_helpers_are_stable_and_use_existing_canonical_json_contract(tmp_path: Path) -> None:
    payload = {"z": "á", "a": [2, 1]}
    source = tmp_path / "source.bin"
    source.write_bytes(b"identity bytes")

    assert canonical_json(payload) == '{"a":[2,1],"z":"á"}'
    assert sha256_content(payload) == "eac475f0d67a3fd63c48d31ce41f253d7926ea36ac8e2c7642761eb7abd89894"
    assert sha256_bytes(b"identity bytes") == sha256_file(source)

