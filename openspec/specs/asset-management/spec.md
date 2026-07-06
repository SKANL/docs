# Asset Management Specification

## Purpose

Manage document assets (embedded files, images, media) with configurable kind validation so the harness supports multiple asset types without hardcoded format assumptions.

## Requirements

### Requirement: Asset-Kind Validation

The system MUST validate assets against a configurable asset-kind concept (allowed extensions per kind) instead of a hardcoded ".docx-only" check.

#### Scenario: Accept an allowed asset kind

- GIVEN an asset-kind configuration that allows ".docx" (and any other configured kind)
- WHEN an asset of an allowed kind is added
- THEN it is accepted and stored under the document's assets directory

#### Scenario: Reject a disallowed asset kind

- GIVEN an asset-kind configuration
- WHEN an asset whose type is not in the allowed set is added
- THEN the system raises a clear error naming the rejected file and its type

#### Scenario: DOCX-only configuration behaves as before

- GIVEN an asset-kind configuration that only allows "docx"
- WHEN a non-docx file is added
- THEN it is rejected, preserving prior behavior for documents that only use DOCX assets

### Requirement: Asset Repository Port Generalization

The `AssetRepository` port MUST expose a kind-agnostic listing method (e.g., `list_assets(directory, kind)`) replacing the DOCX-specific `glob_docx`.

#### Scenario: List assets by kind

- GIVEN an assets directory containing files of multiple configured kinds
- WHEN `list_assets` requests a specific kind (e.g., "docx")
- THEN only files matching that kind are returned

#### Scenario: Existing DOCX listing behavior preserved

- GIVEN an assets directory with only `.docx` files
- WHEN assets are listed for kind "docx"
- THEN the result matches what the previous `glob_docx`-based listing returned
