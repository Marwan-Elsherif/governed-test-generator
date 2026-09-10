# Audit — 2026-09-10T13-48-36Z_TKT-3_490afa

**Verdict: FAIL**  ·  policy held: yes  ·  ticket TKT-3 — Order items quantity constraint

- no feature file was produced inside the declared scope

## Session

| field | value |
|---|---|
| started | 2026-09-10T13:48:36Z |
| finished | 2026-09-10T13:48:36Z (cli:finish) |
| session id | n/a |
| agent | feature-author `f34c81193713` |
| model | not recorded |
| hooks active | no |
| integrity | not_configured |
| events recorded | 4 |

## Classification

- declared: **db**  ·  expected: db  ·  match: **exact**
- rationale: Database constraint on order_items.quantity requiring positive values.
- evidence: “order_items.quantity currently accepts any integer. It must be a positive integer.”
- evidence: “Inserting or updating an order_items row with quantity ≤ 0 is rejected.”

## Conventions in play

| domain | file | sha256 | fingerprint | served at |
|---|---|---|---|---|
| db | conventions/db.md | `3d7d6a02d6d0` | `3d7d6a02` | 2026-09-10T13:48:36Z |

- direct reads of conventions denied: 0
- leak scan: 0 tool responses scanned, 0 hit(s)

## Policy

- allowed write paths: features/db/**
- tool calls: 0 (0 allowed, 0 denied)
- terminal: 0 allowed, 0 denied

## Outputs

_none_
## Git scope check

- HEAD at start `962c35c7dfcd`, at finish `962c35c7dfcd`
- no files changed

## Validation history

_no validate calls during the run_

_Raw record: `audit.json`; events: `events.jsonl`; served text: `served/`_
