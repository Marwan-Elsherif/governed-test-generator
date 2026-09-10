@db @exemplar @table-products @migration-0003_products_price_check
Feature: DB products - price_cents must not be negative

  Background:
    Given the database schema is at migration "0002_carts_status"

  @up @rollback @ac-1
  Scenario: products: the up migration adds the check constraint
    When I apply migration "0003_products_price_check"
    Then the migration succeeds
    And a constraint "chk_products_price_cents_non_negative" exists on "products"

  @up @rollback @ac-2
  Scenario: products: the up migration refuses when a negative price already exists
    Given the following rows exist in "products":
      | id                                   | sku      | name      | category | price_cents |
      | 00000000-0000-4000-8000-000000000001 | TEST-NEG | Bad price | test     | -100        |
    When I apply migration "0003_products_price_check"
    Then the migration fails with "1 existing row(s) have price_cents < 0"
    And no constraint "chk_products_price_cents_non_negative" exists on "products"

  @rollback @ac-3
  Scenario: products: a negative price is rejected once the constraint exists
    Given migration "0003_products_price_check" is applied
    When I insert into "products":
      | id                                   | sku        | name      | category | price_cents |
      | 00000000-0000-4000-8000-000000000002 | TEST-NEG-2 | Bad price | test     | -1          |
    Then the statement fails with constraint "chk_products_price_cents_non_negative"

  @down @rollback @ac-4
  Scenario: products: the down migration removes the constraint
    Given migration "0003_products_price_check" is applied
    When I roll back migration "0003_products_price_check"
    Then the migration succeeds
    And no constraint "chk_products_price_cents_non_negative" exists on "products"
