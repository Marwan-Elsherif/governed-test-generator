# Database conventions

PostgreSQL 16. Migrations are plain SQL files applied in filename order by
`dbmate`. The current schema is checked in at `shop/db/schema.sql` and is
regenerated from the migrations rather than edited by hand.

## Migration files

Named `NNNN_snake_case_description.sql`, four digits, no gaps in the sequence.
Every migration has both sections, in this order:

```sql
-- migrate:up
ALTER TABLE ...;

-- migrate:down
ALTER TABLE ...;
```

The rules, all of which are checked in review:

- **Every migration is reversible.** The down section returns the schema to
  exactly the state before the up section ran. A down section that is empty, or
  that says a comment like "not reversible", does not pass review.
- **A migration is never edited once merged.** Corrections are a new migration.
- **Adding a constraint to a column that already holds data means verifying
  first.** Check for rows that would violate the new constraint and raise, so
  the migration fails loudly and the deploy stops. Silently skipping or fixing
  offending rows hides a data problem. `0003_products_price_check.sql` is the
  reference for this.
- **One concern per migration.** Adding a column and backfilling it are two
  migrations, so the backfill can be rerun without re-adding the column.

## Naming

| Object | Pattern | Example |
|---|---|---|
| Primary key | `pk_<table>` | `pk_orders` |
| Foreign key | `fk_<table>_<column>` | `fk_order_items_order_id` |
| Unique | `uq_<table>_<columns>` | `uq_cart_items_cart_id_product_id` |
| Check | `chk_<table>_<column>_<rule>` | `chk_cart_items_quantity_positive` |
| Index | `idx_<table>_<columns>` | `idx_products_active_created_at` |

Constraints are always named explicitly. A constraint added without a name gets
a generated one that differs between environments, which makes it impossible to
write a test that asserts on the constraint by name.

Columns holding money are integer cents and end in `_cents`. Timestamps are
`TIMESTAMPTZ` and end in `_at`.

## Test data

Automated tests write rows with identifiers in the reserved UUID range
`00000000-0000-4000-8000-XXXXXXXXXXXX`, choosing the final block themselves. The
range is reserved by convention: nothing outside automated testing writes an
identifier that begins `00000000-`, so a stray fixture row is always
identifiable as one, and a cleanup can safely delete by prefix.

A test that writes rows is responsible for removing them, whether it passed or
failed. Prefer a transaction that is rolled back. Where a test must commit, for
example to observe a constraint firing on a separate connection, it deletes what
it created afterwards.

Fixture rows never reuse an identifier from another test. Tests run in parallel
against the same database and a shared identifier makes failures that only
appear under load.

## Things worth knowing

`cart_items` and `order_items` look like the same table twice, but they are not.
A cart line points at a product and reads its price live. An order line copies
the name and unit price at the moment the order is placed, so that a later price
change does not rewrite history. That is why `order_items` carries `name` and
`unit_price_cents` and `cart_items` does not.

`orders.cart_id` is nullable and has no cascade. Carts are operational data and
may eventually be cleaned up; an order must survive that.
