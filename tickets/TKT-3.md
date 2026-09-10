---
id: TKT-3
title: Order items quantity constraint
---

*Transcribed verbatim from the challenge brief. Acceptance criteria are
numbered here (wording unchanged) to support `@ac-N` traceability in
generated feature files.*

## Description

`order_items.quantity` currently accepts any integer. It must be a
positive integer.

## Acceptance Criteria

1. Inserting or updating an `order_items` row with quantity ≤ 0 is rejected.
2. Existing rows are unaffected by the migration; the migration fails if any existing row would violate the constraint.
3. The constraint is reversible (down migration removes it).
