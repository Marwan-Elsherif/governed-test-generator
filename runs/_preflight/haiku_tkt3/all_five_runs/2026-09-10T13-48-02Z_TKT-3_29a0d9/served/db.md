# db conventions

Version 1. Applies to `features/db/**`, together with `conventions/common.md`.
Rule IDs are checked mechanically by `python3 tools/gov.py validate`; a rule
is FAIL unless marked WARN. Worked example: `features/db/products_price_check.feature`.

## What a db feature file is

A data-integrity specification: what the schema permits, what it rejects, and
how a migration moves between the two. Scenarios speak in tables, columns,
constraints, indexes and migrations. They never mention requests, screens or
shoppers. Every scenario that writes data leaves the database as it found it.

The schema is `shop/db/schema.sql`; migrations and their format, the naming
patterns and the test-data policy are in `shop/db/README.md`.

## Rules

- **DB-01 Title.** `Feature: DB <table> - <concern>`, where `<table>` is a
  table in the schema, spelled exactly.
- **DB-02 Feature tags.** The feature line carries `@db` and `@table-<table>`
  for the title's table. A feature that applies or rolls back a migration also
  carries `@migration-<NNNN>_<slug>`: an existing migration id, or, for a
  migration this ticket introduces, exactly the next number in sequence with
  a snake_case slug.
- **DB-03 Background.** A `Background:` exists and its first step is
  `Given the database schema is at migration "<NNNN>_<slug>"`, naming an
  existing migration: the state before this feature's changes.
- **DB-04 Rollback.** Every scenario containing a write step (see DB-08) is
  tagged `@rollback`.
- **DB-05 Reversibility.** A feature carrying `@migration-...` has at least one
  scenario tagged `@up` that applies the migration and at least one tagged
  `@down` that rolls it back and asserts the schema object is gone.
- **DB-06 Names.** Every quoted table exists in the schema. Every column in a
  data table header exists on that table. Constraint names follow
  `chk_<table>_<column>_<rule>`, `fk_<table>_<column>`, `uq_<table>_<columns>`,
  `pk_<table>`; index names follow `idx_<table>_<columns>`.
- **DB-07 Fixture ids.** Every UUID literal is from the reserved test range
  `00000000-0000-4000-8000-XXXXXXXXXXXX`.
- **DB-08 Step catalogue.** Write steps:
  `Given the following rows exist in "<table>":` with a data table;
  `Given migration "<id>" is applied`;
  `When I insert into "<table>":` with a data table;
  `When I update "<table>" setting <column> to <value> where <condition>`;
  `When I delete from "<table>" where <condition>`;
  `When I apply migration "<id>"`; `When I roll back migration "<id>"`.
  Assertion steps (every `Then`, and `And`/`But` continuing one) are one of:
  `the statement succeeds`;
  `the statement fails with constraint "<name>"`;
  `the migration succeeds`;
  `the migration fails with "<message fragment>"`;
  `a constraint "<name>" exists on "<table>"`;
  `no constraint "<name>" exists on "<table>"`;
  `an index "<name>" exists on "<table>" (<columns>)`;
  `no index "<name>" exists on "<table>"`;
  `the row count of "<table>" is <n>`;
  `the rows in "<table>" are unchanged`.
- **DB-09 Scenario names.** `<table>: <expectation>`, where `<table>` is the
  feature's table, for example `Scenario: order_items: a zero quantity is rejected`.
- **DB-10 Forbidden terms.** `http`, `status code`, `response status`,
  `endpoint`, `request`, `response`, `json`, `click`, `button`, `shopper`,
  `i should see`, `the page`, `screen`.

## Target state (C-07 for db)

"The specification" is `schema.sql` and the migrations folder. "The thing
under test" is every constraint, index or migration id the feature names. If
any is absent from the specification, the feature is `@spec-pending`; a new
migration id is then provisional and is assigned for real at implementation.
The run summary names the new objects.

## Writing it well

A migration feature has four shapes of scenario: the up applies cleanly, the
up refuses when existing data would violate it, the new rule rejects bad
writes, the down removes it. Insert only the rows the scenario needs, with
explicit ids from the reserved range, and let `@rollback` clean up.
