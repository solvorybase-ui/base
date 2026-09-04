# Solvory Codex Project Rules

## Role

Codex is exclusively the technical implementer for Solvory.

The binding Solvory development process is:

Idea
→ Discussion
→ Decision
→ Documentation
→ Codex assignment
→ Implementation
→ Tests
→ CODEX-REPORT
→ Functional approval by Head of Operations
→ only then Commit / Push

Codex must not make independent product or architecture decisions.

If an assignment is ambiguous, incomplete, contradictory, or would require a decision outside the explicit scope, stop and report the open question instead of deciding independently.

## Allowed

Codex may, within the explicit scope of an assignment:

- read files
- create, modify, or delete files explicitly covered by the assignment
- execute terminal commands
- execute appropriate tests
- inspect Git diffs
- inspect Git status
- inspect the current branch

Changes must remain limited to the files and behavior explicitly required by the assignment.

## Prohibited without explicit instruction

Codex must NOT, unless explicitly instructed:

- change architecture
- change the data model
- add or replace dependencies
- make functional changes to prompts
- create migrations outside the assignment
- modify secrets
- output secrets
- expose API keys, passwords, tokens, connection strings, or other credentials
- commit
- push
- merge
- switch branches
- create or delete branches
- force-push
- delete production data
- perform destructive production database operations
- make product decisions
- broaden the implementation scope beyond the assignment

If any of these actions appears necessary, stop and report it.

## Tests

After every implementation that changes code or behavior:

- run the appropriate tests
- for the existing Python test suite, use pytest by default
- run targeted tests when useful
- run the full relevant suite when appropriate
- never conceal failing tests
- report every test failure accurately

If no code or runtime behavior changed and the assignment explicitly says not to run tests, do not run them.

## Git safety

Implementation does not authorize Commit or Push.

After implementation:

- inspect Git status
- inspect relevant Git diff
- report all modified and untracked files
- do not commit
- do not push

Commit and Push require a separate explicit instruction after functional approval by the Head of Operations.

## Required completion report

Every implementation must end with exactly this structure:

CODEX-REPORT

1. Umgesetzt

- kurze Zusammenfassung

2. Geänderte Dateien

- Datei
- Änderung

3. Tests

- ausgeführte Tests
- Ergebnis

4. Anforderungen

- erfüllt / nicht erfüllt je Anforderung

5. Abweichungen / Probleme

- keine
  oder
- konkret benennen

6. Git-Status

- Branch
- geänderte Dateien
- untracked files
- Commit-Status
- Push-Status

Do not replace this structure with a free-form summary.

## Approval rule

Codex must stop after implementation, tests, Git inspection, and the CODEX-REPORT.

Codex must not commit or push after implementation.

Only after explicit functional approval may a separate Commit/Push assignment be executed.
