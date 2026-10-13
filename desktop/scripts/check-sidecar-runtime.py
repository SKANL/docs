"""Smoke-test the packaged Windows sidecar against a fresh workspace."""

from __future__ import annotations

from sidecar_harness import running_sidecar


def main() -> int:
    with running_sidecar("docs-sidecar-runtime-") as sidecar:
        if sidecar.health != {"protocol": "docs-sidecar/v1", "ready": True}:
            raise SystemExit(f"unexpected sidecar health response: {sidecar.health!r}")
        template = sidecar.workspace / "templates" / "documento-generico.json"
        if not template.is_file():
            raise SystemExit("fresh packaged sidecar did not seed built-in templates")
        print("packaged sidecar runtime smoke test passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
