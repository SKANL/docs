"""PyInstaller entry point for the packaged docs sidecar (see desktop/scripts/build-sidecar.ps1)."""

from docs.sidecar import main

if __name__ == "__main__":
    raise SystemExit(main())
