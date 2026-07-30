# Template Provisioning Specification

## Purpose

Ship usable document templates with the harness itself, so a document can be started without a project-specific fixture already living in the consuming repo.

## Requirements

### Requirement: Built-In Templates as Package Data

The system MUST ship at least one built-in template as package data (installed with the harness), independent of any consuming repository's `tests/fixtures/` or similar local paths.

#### Scenario: Built-in template available after install

- GIVEN the `docs` package is installed with no project-local template fixtures present
- WHEN a built-in template is requested
- THEN it is found and usable without any extra file present in the workspace

### Requirement: `template list --available` Command

The system MUST provide a command listing all built-in templates shipped with the package, distinct from templates already copied into the active workspace.

#### Scenario: List built-in templates

- GIVEN one or more built-in templates ship with the package
- WHEN `template list --available` runs
- THEN it prints each built-in template's identifier
- AND does not require a workspace to already contain a copy

### Requirement: `template use <builtin>` Command

The system MUST provide a command that copies a named built-in template into the active workspace, making it usable by the standard template machinery.

#### Scenario: Instantiate a built-in template

- GIVEN a built-in template identifier from `template list --available`
- WHEN `template use <builtin>` runs
- THEN the template is copied into the workspace's templates directory
- AND is subsequently usable like any workspace-local template

#### Scenario: Unknown built-in identifier

- GIVEN an identifier not present in the built-in template set
- WHEN `template use <identifier>` runs
- THEN the system raises a clear error naming the unknown identifier
- AND does not partially copy files
