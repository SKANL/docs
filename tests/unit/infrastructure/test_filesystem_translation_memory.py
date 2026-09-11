from docs.domain.translation_memory_key import memory_key
from docs.infrastructure.translate.filesystem_translation_memory import (
    FilesystemTranslationMemory,
)


def test_the_same_inputs_produce_the_same_key():
    assert memory_key("Hello", "en", "es", "llm-v1", "g1") == memory_key(
        "Hello", "en", "es", "llm-v1", "g1"
    )


def test_every_component_changes_the_key():
    base = memory_key("Hello", "en", "es", "llm-v1", "g1")
    assert memory_key("Hello!", "en", "es", "llm-v1", "g1") != base
    assert memory_key("Hello", "en", "fr", "llm-v1", "g1") != base
    assert memory_key("Hello", "de", "es", "llm-v1", "g1") != base
    assert memory_key("Hello", "en", "es", "llm-v2", "g1") != base
    assert memory_key("Hello", "en", "es", "llm-v1", "g2") != base


def test_components_cannot_collide_by_concatenation():
    assert memory_key("ab", "c", "es", "e", "g") != memory_key("a", "bc", "es", "e", "g")


def test_a_stored_translation_is_read_back(tmp_path):
    memory = FilesystemTranslationMemory(tmp_path)
    memory.put("k1", "Hello", "Hola")
    assert memory.get("k1") == "Hola"


def test_a_missing_key_returns_none(tmp_path):
    assert FilesystemTranslationMemory(tmp_path).get("absent") is None


def test_the_cache_survives_a_new_instance(tmp_path):
    FilesystemTranslationMemory(tmp_path).put("k1", "Hello", "Hola")
    assert FilesystemTranslationMemory(tmp_path).get("k1") == "Hola"


def test_a_corrupt_entry_is_a_miss_not_a_crash(tmp_path):
    memory = FilesystemTranslationMemory(tmp_path)
    memory.put("k1", "Hello", "Hola")
    (tmp_path / "k1.json").write_text("{ not json", encoding="utf-8")
    assert memory.get("k1") is None


def test_writes_leave_no_scratch_behind(tmp_path):
    memory = FilesystemTranslationMemory(tmp_path)
    memory.put("k1", "Hello", "Hola")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "k1.json"]
    assert leftovers == []


def test_non_ascii_translations_round_trip(tmp_path):
    memory = FilesystemTranslationMemory(tmp_path)
    memory.put("k1", "Attention", "Atención: pingüino, año")
    assert FilesystemTranslationMemory(tmp_path).get("k1") == "Atención: pingüino, año"


def test_the_stored_entry_is_deterministic_on_disk(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    FilesystemTranslationMemory(a).put("k1", "Hello", "Hola")
    FilesystemTranslationMemory(b).put("k1", "Hello", "Hola")
    assert (a / "k1.json").read_bytes() == (b / "k1.json").read_bytes()
