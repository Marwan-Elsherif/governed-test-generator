# Audit — 2026-09-10T15-42-46Z_TKT-1_cf700b

**Verdict: PASS**  ·  policy held: yes  ·  ticket TKT-1 — Product search filters

- policy held, outputs valid, classification matches the expected domains

## Session

| field | value |
|---|---|
| started | 2026-09-10T15:42:46Z |
| finished | 2026-09-10T15:43:34Z (cli:finish) |
| session id | 6d13da20-3339-474f-b2d4-c8c5fc485896 |
| agent | feature-author `f34c81193713` |
| model | not recorded |
| client | copilot-agent 0.64.1 on VS Code 1.136.2 |
| hooks active | yes |
| integrity | not_configured |
| events recorded | 21 |

## Classification

- declared: **ui**  ·  expected: ui  ·  match: **exact**
- rationale: The ticket is about shopper-facing product listing filters and URL behavior, which are UI concerns.
- evidence: “Category filter shows only products in the selected category.”
- evidence: “Applying a filter does not reload the page; the URL reflects the active filters.”

## Conventions in play

| domain | file | sha256 | fingerprint | served at |
|---|---|---|---|---|
| ui | conventions/ui.md | `3f9a4194adc6` | `3f9a4194` | 2026-09-10T15:42:58Z |

- direct reads of conventions denied: 0
- leak scan: 7 tool responses scanned, 0 hit(s)

## Policy

- allowed write paths: features/ui/**
- tool calls: 8 (8 allowed, 0 denied)
- terminal: 3 allowed, 0 denied

## Outputs

### `features/ui/product_search_filters.feature` — PASS

- domain ui, 5 scenario(s), sha256 `117cef68465c`, snapshot `output/product_search_filters.feature`
- spec-pending: yes; adds: Product Listing: Category filter, Product Listing: Home & Garden, Product Listing: Kitchen, Product Listing: Maximum price field, Product Listing: Minimum price field
- acceptance criteria covered: ac-1, ac-2, ac-3, ac-4, ac-5

## Git scope check

- HEAD at start `75970ad281c9`, at finish `75970ad281c9`

| path | status | domain | in scope |
|---|---|---|---|
| features/ui/product_search_filters.feature | ?? | ui | yes |

## Validation history

1. 2026-09-10T15:43:26Z `features/ui/product_search_filters.feature` → PASS

Cross-check (each output run against the other domains' rules; must fail):
- `features/ui/product_search_filters.feature`: api: 33 failure(s), db: 24 failure(s)

## Notes

- Real result, verified independently: classification ui only, exact match. 8 tool calls, zero denials, zero out-of-scope changes. Five scenarios covering all five acceptance criteria, correctly spec-pending for the new filter controls.
- Found by reading the output, not by the validator: this run's frozen adds_to_specification lists 'Home & Garden' and 'Kitchen' as new page elements alongside the genuinely new controls (Category filter, Minimum/Maximum price field). Those two are category VALUES named in Then-step prose ('...products in the "Home & Garden" category'), not controls -- the element-extraction regex matched the same the "..." shape purely by coincidence of English wording, since it scanned every step rather than only the When steps where this domain's own grammar (UI-06/UI-07) says a real element reference can appear. It did not cause a false failure (the file was already correctly @spec-pending for the real new controls), only an inaccurate detail in what the audit reports as newly added.
- Fixed afterward: element extraction (govlib/rules_ui.py, used by UI-08 and target_state) now scans only When steps. Re-validating features/ui/product_search_filters.feature today reports exactly the three real controls under adds_to_specification, nothing else; verdict and outputs on this frozen run are left exactly as they were at finish time, per the same frozen-facts principle used for the earlier findings on TKT-2 and TKT-6.

_Raw record: `audit.json`; events: `events.jsonl`; served text: `served/`_
