# gov: ticket=TKT-3 domain=db conventions=db@3d7d6a02
@db @table-order_items @migration-0004_order_items_quantity_positive @spec-pending @TKT-3
Feature: DB order_items - quantity must be positive

  Background:
    Given the database schema is at migration "0003_products_price_check"

  @up @rollback @ac-1
  Scenario: order_items: the up migration adds the positive quantity constraint
    When I apply migration "0004_order_items_quantity_positive"
    Then the migration succeeds
    And a constraint "chk_order_items_quantity_positive" exists on "order_items"

  @up @rollback @ac-2
  Scenario: order_items: the up migration preserves valid existing rows
    Given the following rows exist in "order_items":
      | id                                   | order_id                             | product_id                           | name       | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000001 | 00000000-0000-4000-8000-000000000101 | 00000000-0000-4000-8000-000000000201 | Test item  | 2        | 100              |
    When I apply migration "0004_order_items_quantity_positive"
    Then the migration succeeds
    And the rows in "order_items" are unchanged

  @up @rollback @ac-2
  Scenario: order_items: the up migration refuses an existing non-positive quantity
    Given the following rows exist in "order_items":
      | id                                   | order_id                             | product_id                           | name        | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000002 | 00000000-0000-4000-8000-000000000102 | 00000000-0000-4000-8000-000000000202 | Bad item    | 0        | 100              |
    When I apply migration "0004_order_items_quantity_positive"
    Then the migration fails with "1 existing row(s) have quantity <= 0"
    And no constraint "chk_order_items_quantity_positive" exists on "order_items"

  @rollback @ac-1
  Scenario: order_items: an inserted non-positive quantity is rejected
    Given migration "0004_order_items_quantity_positive" is applied
    When I insert into "order_items":
      | id                                   | order_id                             | product_id                           | name        | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000003 | 00000000-0000-4000-8000-000000000103 | 00000000-0000-4000-8000-000000000203 | Bad item    | -1       | 100              |
    Then the statement fails with constraint "chk_order_items_quantity_positive"

  @rollback @ac-1
  Scenario: order_items: an updated non-positive quantity is rejected
    Given migration "0004_order_items_quantity_positive" is applied
    Given the following rows exist in "order_items":
      | id                                   | order_id                             | product_id                           | name       | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000004 | 00000000-0000-4000-8000-000000000104 | 00000000-0000-4000-8000-000000000204 | Test item | 1        | 100              |
    When I update "order_items" setting quantity to 0 where id = "00000000-0000-4000-8000-000000000004"
    Then the statement fails with constraint "chk_order_items_quantity_positive"

  @down @rollback @ac-3
  Scenario: order_items: the down migration removes the positive quantity constraint
    Given migration "0004_order_items_quantity_positive" is applied
    When I roll back migration "0004_order_items_quantity_positive"
    Then the migration succeeds
    And no constraint "chk_order_items_quantity_positive" exists on "order_items"
