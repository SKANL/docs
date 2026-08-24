# Workspace Config Specification

## Purpose

Let any code agent point the harness at a workspace without per-call env vars or hardcoded paths, by persisting workspace roots to a config file and bootstrapping it with one command.

Implemented by the `Workspace` value object and the `workspace_config` resolution rules, bootstrapped into a real directory tree by the `doc_init` command.

## Requirements

### Requirement: Persisted Workspace Configuration

The system MUST support a persisted config file declaring workspace roots (inbox, documents, templates, etc.) so a workspace's location is not re-supplied on every invocation.

#### Scenario: Config file present

- GIVEN a workspace config file exists at the workspace root
- WHEN any `docs` command runs without env vars set
- THEN the command resolves workspace roots from the config file

#### Scenario: Config file absent

- GIVEN no workspace config file exists
- WHEN a `docs` command runs
- THEN the system falls back to env vars, then defaults, without erroring

### Requirement: Config Precedence Resolution

Workspace root resolution MUST follow strict precedence: config file → environment variable → built-in default. A higher-precedence source MUST always win when present, and the resolution order MUST be stable across runs.

#### Scenario: Config overrides env var

- GIVEN a workspace config file sets `inbox_dir` to path X
- AND an env var sets a different path Y for the same root
- WHEN roots are resolved
- THEN path X (from config) is used, not Y

#### Scenario: Env var overrides default when no config

- GIVEN no config file exists
- AND an env var sets `inbox_dir` to path Y
- WHEN roots are resolved
- THEN path Y is used, not the built-in default

#### Scenario: Default used when nothing else is set

- GIVEN no config file and no relevant env var
- WHEN roots are resolved
- THEN the existing cwd-relative default applies (no regression for current users)

### Requirement: `doc init` Bootstrap Command

The system MUST provide a `doc init` command that creates the workspace directory layout and writes a config file capturing the resolved roots, so a fresh agent can bootstrap a workspace in one call.

#### Scenario: Bootstrap a fresh workspace

- GIVEN an empty target directory
- WHEN `doc init` runs against it
- THEN the standard workspace directories are created
- AND a config file is written recording the workspace roots

#### Scenario: Re-running init on an existing workspace

- GIVEN a workspace already initialized by `doc init`
- WHEN `doc init` runs again
- THEN it does not overwrite existing documents or config values without explicit confirmation
- AND it reports the workspace is already initialized

### Requirement: Declared Config Vocabulary

The configuration keys the harness reads MUST be declared in one place, and
that declaration MUST be mechanically proven to match the keys the source
actually reads — in both directions. A key the code reads but the declaration
omits leaves a hole in near-miss detection; a key the declaration names but
nothing reads documents something that no longer exists. Both MUST fail the
build.

#### Scenario: A newly read config key must be declared

- GIVEN a new `config["..."]` access is added anywhere under `src/docs`
- WHEN the test suite runs
- THEN it fails until that key appears in the declared vocabulary

#### Scenario: A vocabulary entry nothing reads must be removed

- GIVEN a declared config key that no longer appears in any source access
- WHEN the test suite runs
- THEN it fails, so the vocabulary cannot drift into fiction

#### Scenario: The scan proves it still finds the config surface

- GIVEN the vocabulary guard runs
- THEN it asserts a non-trivial number of accesses were found, so an AST walk
  that silently stopped matching cannot report agreement by finding nothing
