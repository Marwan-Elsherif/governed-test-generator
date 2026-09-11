# Audit — 2026-09-10T15-51-17Z_TKT-4_0c2d79

**Verdict: PASS**  ·  policy held: yes  ·  ticket TKT-4 — Checkout confirmation

- policy held, outputs valid, classification matches the expected domains

## Session

| field | value |
|---|---|
| started | 2026-09-10T15:51:17Z |
| finished | 2026-09-10T15:52:50Z (cli:finish) |
| session id | 6d13da20-3339-474f-b2d4-c8c5fc485896 |
| agent | feature-author `f34c81193713` |
| model | not recorded |
| client | copilot-agent 0.64.1 on VS Code 1.136.2 |
| hooks active | yes |
| integrity | not_configured |
| events recorded | 38 |
| chat transcript | transcript.raw.jsonl |

## Classification

- declared: **ui, api**  ·  expected: ui, api  ·  match: **exact**
- rationale: The ticket spans the API order-creation contract and the storefront confirmation behavior after checkout submission.
- evidence: “After the shopper submits checkout, the confirmation page must show the order number returned by POST /orders.”
- evidence: “If order creation fails, the shopper stays on the checkout page and sees an error message.”

## Conventions in play

| domain | file | sha256 | fingerprint | served at |
|---|---|---|---|---|
| ui | conventions/ui.md | `3f9a4194adc6` | `3f9a4194` | 2026-09-10T15:51:30Z |
| api | conventions/api.md | `a89c22c308b3` | `a89c22c3` | 2026-09-10T15:51:31Z |

- direct reads of conventions denied: 0
- leak scan: 14 tool responses scanned, 0 hit(s)

## Policy

- allowed write paths: features/ui/**, features/api/**
- tool calls: 15 (15 allowed, 0 denied)
- terminal: 4 allowed, 0 denied

## Outputs

### `features/api/orders_post.feature` — PASS

- domain api, 2 scenario(s), sha256 `a0542883913c`, snapshot `output/orders_post.feature`
- spec-pending: no
- acceptance criteria covered: ac-1, ac-2, ac-3, ac-4

### `features/ui/checkout_confirmation.feature` — PASS

- domain ui, 2 scenario(s), sha256 `47158405b0b1`, snapshot `output/checkout_confirmation.feature`
- spec-pending: no
- acceptance criteria covered: ac-1, ac-2, ac-3, ac-4

## Git scope check

- HEAD at start `d46956aa72bb`, at finish `d46956aa72bb`

| path | status | domain | in scope |
|---|---|---|---|
| features/api/orders_post.feature | ?? | api | yes |
| features/ui/checkout_confirmation.feature | ?? | ui | yes |

## Validation history

1. 2026-09-10T15:52:20Z `features/api/orders_post.feature` → FAIL (6 failure(s): API-05:13, API-05:27, API-05:29, API-05:9, C-05:17, C-06:3)
2. 2026-09-10T15:52:20Z `features/ui/checkout_confirmation.feature` → FAIL (2 failure(s): C-06:3, UI-06:14)
3. 2026-09-10T15:52:45Z `features/api/orders_post.feature` → PASS
4. 2026-09-10T15:52:45Z `features/ui/checkout_confirmation.feature` → PASS

Cross-check (each output run against the other domains' rules; must fail):
- `features/api/orders_post.feature`: db: 11 failure(s), ui: 15 failure(s)
- `features/ui/checkout_confirmation.feature`: api: 12 failure(s), db: 11 failure(s)

## Notes

- Real result, verified independently: classification ui+api, exact match. 15 tool calls, zero denials, zero out-of-scope changes. Both outputs PASS with full AC coverage. Confirmed POST /orders and every referenced UI element already exist in shop/ (openapi.yaml, pages.md), so spec_pending=false on both outputs is correct, not a missed check.
- Content observation, not a rule violation: AC-2 is a compound claim, 'returns 422 and no order is created.' The api scenario tagged @ac-2 asserts only the 422 status and error code; it never independently verifies that no order was actually created (e.g. a follow-up GET /orders showing the count unchanged). Unlike the TKT-6 method mismatch and TKT-1 element-extraction bugs, this was not turned into a new validator rule: recognising 'this criterion claims an absent side effect and the scenario must independently prove that absence' is not a clean, low-false-positive mechanical check the way HTTP-method matching was -- many legitimate test suites treat a correct error status as sufficient proof of non-creation, and a rule flagging every such case would be opinionated rather than a crisp signal. Left as a human-reviewable observation rather than encoded as a check that might be wrong as often as it is right.
- Also observed, not a problem: the agent read features/api/cart_total_get.feature (TKT-2's real output) as a reference in addition to the exemplar it was pointed to, and read .github/copilot-instructions.md directly. Both correctly allowed (own-domain reads); noted only because it shows the agent using accumulated real output as context once the repo has some history, not just the designated exemplar.

_Raw record: `audit.json`; events: `events.jsonl`; served text: `served/`; chat transcript: `transcript.raw.jsonl`_
