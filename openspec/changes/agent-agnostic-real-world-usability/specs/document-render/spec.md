# Delta for Document Render

## ADDED Requirements

### Requirement: Document-Order Figure/Table Numbering at Build Time

The system MUST assign figure/table numbers automatically, in document order, at build/assemble time. Authors MUST use stable symbolic labels/anchors and "Ver {ref}"-style references in section Markdown; the build MUST resolve these to concrete numbers and cross-references. Authors and agents MUST NOT be required to hand-assign or hand-renumber `Figura N`/`Tabla N`.

#### Scenario: Figures numbered in document order

- GIVEN sections referencing figures via symbolic labels, in a known document order
- WHEN the document is built
- THEN each figure receives a sequential number matching its position in document order

#### Scenario: Cross-reference resolves to the assigned number

- GIVEN a section containing "Ver {ref}" pointing to a symbolic figure label
- WHEN the document is built
- THEN the reference resolves to the figure's assigned number (e.g., "Ver Figura 3")

#### Scenario: Reordering sections renumbers without manual edits

- GIVEN a document previously built with figures numbered per the original section order
- WHEN sections are reordered and the document is rebuilt with no manual number edits
- THEN figures are renumbered to match the new document order
- AND all "Ver {ref}" cross-references still resolve correctly

#### Scenario: Unresolvable reference is reported, not silently dropped

- GIVEN a "Ver {ref}" pointing to a label with no matching figure/table
- WHEN the document is built
- THEN the build reports a clear error naming the unresolved label

### Requirement: Evidence-Aware Review Precision

Review heuristics (subjective-word checks, required-content keyword checks, contested-stack-term checks) MUST require concrete evidence in context before flagging, so legitimate terms (e.g., a project genuinely using "Firebase") and legitimate subjective/plural-token usage are not flagged as violations while genuine issues are still caught.

#### Scenario: Legitimate stack term not flagged

- GIVEN a section using a technology term (e.g., "Firebase") that matches the actual project's ingested facts
- WHEN `review-section` runs
- THEN no contested-stack-term finding is raised for that term

#### Scenario: Genuinely contested/conflicting stack term still flagged

- GIVEN a section using a technology term that conflicts with the ingested facts about the project's actual stack
- WHEN `review-section` runs
- THEN a contested-stack-term finding is raised, naming the conflict

#### Scenario: Subjective-word check requires context, not bare substring

- GIVEN a section using a word from the subjective-word list in a non-subjective, evidenced context
- WHEN `review-section` runs
- THEN it is not flagged as an unsupported subjective claim
