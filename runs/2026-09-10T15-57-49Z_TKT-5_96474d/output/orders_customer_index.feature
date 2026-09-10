# gov: ticket=TKT-5 domain=db conventions=db@3d7d6a02
@db @table-orders @TKT-5 @spec-pending @migration-0004_orders_customer_index
Feature: DB orders - customer_id lookup index

  Background:
    Given the database schema is at migration "0003_products_price_check"

  @up @rollback @ac-1 @ac-2 @ac-3 @ac-4
  Scenario: orders: the up migration adds the customer_id index
    When I apply migration "0004_orders_customer_index"
    Then the migration succeeds
    And an index "idx_orders_customer_id" exists on "orders" (customer_id)

  @down @rollback @ac-extra
  Scenario: orders: the down migration removes the customer_id index
    Given migration "0004_orders_customer_index" is applied
    When I roll back migration "0004_orders_customer_index"
    Then the migration succeeds
    And no index "idx_orders_customer_id" exists on "orders"
