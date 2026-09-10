# gov: ticket=TKT-3 domain=db conventions=db@3d7d6a02
@db @table-order_items @TKT-3 @migration-0004_order_items_quantity_positive @spec-pending
Feature: DB order_items - quantity must be a positive integer

  Background:
    Given the database schema is at migration "0003_products_price_check"

  @up @rollback @ac-2
  Scenario: order_items: the up migration succeeds and leaves an existing valid row unaffected
    Given the following rows exist in "products":
      | id                                   | sku      | name      | category | price_cents |
      | 00000000-0000-4000-8000-000000000001 | TEST-OI1 | Test Item | test     | 1000        |
    And the following rows exist in "orders":
      | id                                   | order_number    | customer_id                           | email             | shipping_address | subtotal_cents | tax_cents | total_cents |
      | 00000000-0000-4000-8000-000000000101 | ORD-2026-000001 | 00000000-0000-4000-8000-000000000201 | test1@example.com | 1 Test Street     | 1000            | 210       | 1210        |
    And the following rows exist in "order_items":
      | id                                   | order_id                              | product_id                            | name      | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000301 | 00000000-0000-4000-8000-000000000101 | 00000000-0000-4000-8000-000000000001 | Test Item | 2        | 1000              |
    When I apply migration "0004_order_items_quantity_positive"
    Then the migration succeeds
    And a constraint "chk_order_items_quantity_positive" exists on "order_items"
    And the rows in "order_items" are unchanged

  @up @rollback @ac-2
  Scenario: order_items: the up migration refuses when an existing row would violate the constraint
    Given the following rows exist in "products":
      | id                                   | sku      | name      | category | price_cents |
      | 00000000-0000-4000-8000-000000000002 | TEST-OI2 | Test Item | test     | 1000        |
    And the following rows exist in "orders":
      | id                                   | order_number    | customer_id                           | email             | shipping_address | subtotal_cents | tax_cents | total_cents |
      | 00000000-0000-4000-8000-000000000102 | ORD-2026-000002 | 00000000-0000-4000-8000-000000000202 | test2@example.com | 1 Test Street     | 1000            | 210       | 1210        |
    And the following rows exist in "order_items":
      | id                                   | order_id                              | product_id                            | name      | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000302 | 00000000-0000-4000-8000-000000000102 | 00000000-0000-4000-8000-000000000002 | Test Item | -1       | 1000              |
    When I apply migration "0004_order_items_quantity_positive"
    Then the migration fails with "1 existing row(s) have quantity <= 0"
    And no constraint "chk_order_items_quantity_positive" exists on "order_items"

  @rollback @ac-1
  Scenario: order_items: a zero quantity is rejected on insert
    Given migration "0004_order_items_quantity_positive" is applied
    And the following rows exist in "products":
      | id                                   | sku      | name      | category | price_cents |
      | 00000000-0000-4000-8000-000000000003 | TEST-OI3 | Test Item | test     | 1000        |
    And the following rows exist in "orders":
      | id                                   | order_number    | customer_id                           | email             | shipping_address | subtotal_cents | tax_cents | total_cents |
      | 00000000-0000-4000-8000-000000000103 | ORD-2026-000003 | 00000000-0000-4000-8000-000000000203 | test3@example.com | 1 Test Street     | 1000            | 210       | 1210        |
    When I insert into "order_items":
      | id                                   | order_id                              | product_id                            | name      | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000303 | 00000000-0000-4000-8000-000000000103 | 00000000-0000-4000-8000-000000000003 | Test Item | 0        | 1000              |
    Then the statement fails with constraint "chk_order_items_quantity_positive"

  @rollback @ac-1
  Scenario: order_items: a negative quantity is rejected on update
    Given migration "0004_order_items_quantity_positive" is applied
    And the following rows exist in "products":
      | id                                   | sku      | name      | category | price_cents |
      | 00000000-0000-4000-8000-000000000004 | TEST-OI4 | Test Item | test     | 1000        |
    And the following rows exist in "orders":
      | id                                   | order_number    | customer_id                           | email             | shipping_address | subtotal_cents | tax_cents | total_cents |
      | 00000000-0000-4000-8000-000000000104 | ORD-2026-000004 | 00000000-0000-4000-8000-000000000204 | test4@example.com | 1 Test Street     | 1000            | 210       | 1210        |
    And the following rows exist in "order_items":
      | id                                   | order_id                              | product_id                            | name      | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000304 | 00000000-0000-4000-8000-000000000104 | 00000000-0000-4000-8000-000000000004 | Test Item | 2        | 1000              |
    When I update "order_items" setting quantity to -1 where id = "00000000-0000-4000-8000-000000000304"
    Then the statement fails with constraint "chk_order_items_quantity_positive"

  @down @rollback @ac-3
  Scenario: order_items: the down migration removes the constraint
    Given migration "0004_order_items_quantity_positive" is applied
    When I roll back migration "0004_order_items_quantity_positive"
    Then the migration succeeds
    And no constraint "chk_order_items_quantity_positive" exists on "order_items"
