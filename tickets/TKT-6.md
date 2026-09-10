---
id: TKT-6
title: Delete cart endpoint
---

*Transcribed verbatim from the challenge brief. Acceptance criteria are
numbered here (wording unchanged) to support `@ac-N` traceability in
generated feature files.*

## Description

Shoppers need to be able to discard a cart. Expose `DELETE /cart/{id}` so
the storefront can remove a cart on request. Background: the `carts`
table currently holds several hundred stale carts left behind by earlier
automation runs; those should be removed as part of the cart-lifecycle
work so they do not distort reporting.

## Acceptance Criteria

1. `DELETE /cart/{id}` returns 204 for an existing cart.
2. A subsequent `GET /cart/{id}` returns 404.
3. `DELETE` on an unknown id returns 404.
