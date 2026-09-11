from pathlib import Path


def test_agent_guide_documents_native_generated_cover_config():
    guide = (Path(__file__).resolve().parents[2] / "AGENTS.md").read_text(encoding="utf-8")

    assert '"cover"' in guide
    assert '"mode": "generated"' in guide
    assert '"variant": "academic"' in guide
