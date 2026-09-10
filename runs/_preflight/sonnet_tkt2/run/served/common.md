# Common conventions (all domains)

Version 1. These rules apply to every feature file in `features/`, in addition
to the rules of its domain. Rule IDs are checked mechanically by
`python3 tools/gov.py validate`; a rule is FAIL unless marked WARN.

## Header and location

- **C-01 Location.** The file lives at `features/<domain>/<name>.feature`, where
  `<domain>` is `ui`, `api` or `db` and `<name>` is snake_case: lowercase
  letters, digits and underscores only.
- **C-02 Header.** The first line of the file is exactly
  `# gov: ticket=<TKT-n> domain=<domain> conventions=<domain>@<fingerprint>`.
  The domain matches the folder. The fingerprint is the eight-character value
  printed when the conventions were served to you; it is not in any file you
  can read, so copy it from that output. A wrong or missing fingerprint fails.
- **C-03 Structure.** One `Feature:`. At least one `Scenario:` or
  `Scenario Outline:`. Every scenario has at least one `When` and at least one
  `Then`, and no `Given` appears after a `When` or `Then` (`And`/`But` take the
  meaning of the step above them). Every `Scenario Outline` has an `Examples:`
  table with at least one data row.

## Tags

- **C-04 Domain and ticket tags.** The feature line carries `@<domain>` and
  exactly one `@TKT-n` tag naming the ticket. It carries no other domain's
  tag. (Hand-written exemplars carry `@exemplar` instead of a ticket tag.)
- **C-05 Lexicon.** The file contains none of the domain's forbidden terms,
  listed in the domain conventions. Comment lines are not scanned. Matching is
  case-insensitive on whole words.
- **C-06 Traceability.** Every scenario carries at least one `@ac-<n>` tag,
  where `<n>` is the position of an acceptance criterion in the ticket
  (first criterion is `@ac-1`), or `@ac-extra` for a scenario beyond the
  ticket's criteria. Every criterion in the ticket appears on at least one
  scenario. A criterion may be covered by several scenarios.
- **C-07 Target state.** If the thing under test is not in the domain's
  specification yet, the feature line carries `@spec-pending`; if it is already
  specified, it must not. What "the specification" means, and what counts as
  "the thing under test", is defined per domain. The check runs both ways.

## Hygiene

- **C-08 Uniqueness.** Scenario names are unique within the feature. No step
  line is repeated verbatim within one scenario.
- **C-09 Size (WARN).** At most 10 steps per scenario and at most 12 scenarios
  per feature. Split the feature rather than exceed this.

## When the ticket and the specification disagree

Follow the specification in `shop/` and say so in the run summary. The
specification is the contract; the ticket is a request written quickly. A
discrepancy is worth surfacing, not silently resolving either way.
