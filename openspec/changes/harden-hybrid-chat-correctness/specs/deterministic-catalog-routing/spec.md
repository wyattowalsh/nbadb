## ADDED Requirements

### Requirement: Route matching uses deterministic semantic specificity
For every matching catalog pattern, the matcher MUST rank the match by
`match span * 2 - match start`, then by regex-pattern length, then by earlier
catalog order. Catalog order MUST NOT outrank either semantic score.

#### Scenario: Specific phrase overlaps a generic phrase
- **WHEN** `team game log` matches both team-specific and generic game-log patterns
- **THEN** the higher semantic specificity selects the team game-log route regardless of catalog reordering that does not change the scores

#### Scenario: Semantic scores and pattern lengths tie
- **WHEN** two patterns for the same route have equal semantic score and pattern length
- **THEN** the earlier catalog entry provides a deterministic final tie break

### Requirement: A reviewed corpus rejects cross-route co-top matches
The repository MUST maintain a reviewed fixture of representative questions and
their expected routes. Catalog validation MUST evaluate every routed pattern for
each row and MUST reject any highest semantic rank shared by different routes.
Co-top patterns for one route MAY remain valid.

#### Scenario: Corpus row has one semantic winner
- **WHEN** exactly one route owns the highest score and pattern-length rank and it equals the expected route
- **THEN** the corpus row passes independent of lower-ranked incidental matches

#### Scenario: Different routes share the top rank
- **WHEN** patterns from two routes are co-top for a reviewed question
- **THEN** catalog validation fails and reports the question and conflicting route identities before runtime

#### Scenario: Expected route changes
- **WHEN** catalog edits cause the unique winner to differ from the fixture's expected route
- **THEN** validation fails until the matcher or reviewed expectation is intentionally reconciled
