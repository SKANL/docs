from pathlib import Path

from docs.domain.identity import canonical_json, sha256_bytes, sha256_content, sha256_file


def test_identity_helpers_are_stable_and_use_existing_canonical_json_contract(tmp_path: Path) -> None:
    payload = {"z": "á", "a": [2, 1]}
    source = tmp_path / "source.bin"
    source.write_bytes(b"identity bytes")

    assert canonical_json(payload) == '{"a":[2,1],"z":"á"}'
    assert sha256_content(payload) == "eac475f0d67a3fd63c48d31ce41f253d7926ea36ac8e2c7642761eb7abd89894"
    assert sha256_bytes(b"identity bytes") == sha256_file(source)


def test_read_json_object_fails_open_to_none(tmp_path: Path) -> None:
    from docs.domain.identity import read_json_object

    good = tmp_path / "good.json"
    good.write_text('{"a": 1}', encoding="utf-8")
    assert read_json_object(good) == {"a": 1}
    assert read_json_object(tmp_path / "absent.json") is None
    for name, content in {"array": "[1]", "broken": "{", "scalar": "3"}.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
        assert read_json_object(tmp_path / name) is None, name
    binary = tmp_path / "binary.json"
    binary.write_bytes(b"\xff\xfe\x00")
    assert read_json_object(binary) is None
    assert read_json_object(tmp_path) is None  # a directory is OSError, not a crash
