# Delta for Workspace Config

## ADDED Requirements

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
