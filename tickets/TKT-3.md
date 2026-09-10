**TKT-3 — Order items quantity constraint**
*Description:* `order_items.quantity` currently accepts any integer. It must be a positive integer.
*Acceptance criteria:*
- Inserting or updating an `order_items` row with quantity ≤ 0 is rejected.
- Existing rows are unaffected by the migration; the migration fails if any existing row would violate the constraint.
- The constraint is reversible (down migration removes it).
