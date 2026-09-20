# Plugins

Plugins are an extension boundary, not a runtime dependency of the harness.
The native CLI, provenance, verification, and publication paths remain usable
when no plugin is installed.

## Manifest contract

Each plugin is discovered from `plugin.json` and must declare
`schema: "docs.plugin/v1"`, a safe `id`, `version`, an `entrypoint`, and one
or more of `render`, `ingest`, or `transform` capabilities. Optional fields
declare formats, `read_input`/`write_scratch` permissions, network use,
determinism, resource limits, signatures, SBOM data, and toolchain versions.

The registry validates manifests and hashes the canonical JSON. Discovery does
not import or execute plugin code. Untrusted plugins run as subprocesses;
builtin in-process execution is restricted to explicitly allowlisted sources.
The API exposes the registered identity, version, capabilities, trust level,
and digest at `GET /v1/plugins`.

## Safety and reproducibility

Keep plugin inputs data-shaped. A plugin may read declared inputs and write to
its scratch area; it must not mutate source sections or publish artifacts.
Declare positive time, output-size, scratch-size, and scratch-file limits for
production plugins. Set `deterministic: false` when output depends on time,
randomness, network state, or an unpinned toolchain.

Plugins may assist authoring or inspection, but the native v2 pipeline remains
the authority for stage contracts, hashes, QA, provenance, and publication.
When a plugin is unavailable, draft mode reports the degradation and strict or
release policy decides whether the result is publishable.
