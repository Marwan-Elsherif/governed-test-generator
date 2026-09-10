---
id: TKT-2
title: Cart total endpoint
---

*Transcribed verbatim from the challenge brief. Acceptance criteria are
numbered here (wording unchanged) to support `@ac-N` traceability in
generated feature files.*

## Description

Expose `GET /cart/{id}/total` so the storefront can show totals without
fetching the whole cart.

## Acceptance Criteria

1. Returns 200 with `subtotal`, `tax` and `total` for an existing cart.
2. `total` equals `subtotal + tax`; tax is calculated at 21 %.
3. Returns 404 for an unknown cart id.
4. Returns 400 for a malformed cart id.
5. An empty cart returns all three values as 0.
