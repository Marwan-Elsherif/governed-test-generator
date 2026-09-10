# gov: ticket=TKT-3 domain=db conventions=db@3d7d6a02
@db @table-order_items @TKT-3 @migration-0004_order_items_quantity_constraint @spec-pending
Feature: DB order_items - quantity must be positive

  Background:
    Given the database schema is at migration "0003_products_price_check"

  @up @rollback @ac-2
  Scenario: order_items: the up migration adds the check constraint
    When I apply migration "0004_order_items_quantity_constraint"
    Then the migration succeeds
    And a constraint "chk_order_items_quantity_positive" exists on "order_items"

  @up @rollback @ac-2
  Scenario: order_items: the up migration fails when zero quantity already exists
    Given the following rows exist in "order_items":
      | id                                   | order_id                             | product_id                           | name      | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000001 | 00000000-0000-4000-8000-100000000001 | 00000000-0000-4000-8000-200000000001 | Test Item | 0        | 1000             |
    When I apply migration "0004_order_items_quantity_constraint"
    Then the migration fails with "1 existing row(s) have quantity <= 0"
    And no constraint "chk_order_items_quantity_positive" exists on "order_items"

  @rollback @ac-1
  Scenario: order_items: zero quantity is rejected on insert once constraint exists
    Given migration "0004_order_items_quantity_constraint" is applied
    When I insert into "order_items":
      | id                                   | order_id                             | product_id                           | name      | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000002 | 00000000-0000-4000-8000-100000000002 | 00000000-0000-4000-8000-200000000002 | Test Item | 0        | 1000             |
    Then the statement fails with constraint "chk_order_items_quantity_positive"

  @rollback @ac-1
  Scenario: order_items: negative quantity is rejected on update once constraint exists
    Given migration "0004_order_items_quantity_constraint" is applied
    And the following rows exist in "order_items":
      | id                                   | order_id                             | product_id                           | name      | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000003 | 00000000-0000-4000-8000-100000000003 | 00000000-0000-4000-8000-200000000003 | Test Item | 1        | 1000             |
    When I update "order_items" setting quantity to -5 where id = '00000000-0000-4000-8000-000000000003'
    Then the statement fails with constraint "chk_order_items_quantity_positive"

  @down @rollback @ac-3
  Scenario: order_items: the down migration removes the constraint
    Given migration "0004_order_items_quantity_constraint" is applied
    When I roll back migration "0004_order_items_quantity_constraint"
    Then the migration succeeds
    And no constraint "chk_order_items_quantity_positive" exists on "order_items"
