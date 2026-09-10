# gov: ticket=TKT-4 domain=api conventions=api@a89c22c3
@api @post @TKT-4
Feature: API POST /orders

  Background:
    Given the API is available

  @status-201 @ac-1
  Scenario: returns 201 when the cart is valid
    Given a cart exists with id "00000000-0000-4000-8000-000000000101" and items
      | productId | name | quantity | unitPrice |
      | "00000000-0000-4000-8000-000000000111" | "Widget" | 2 | "19.99" |
    When I send a POST request to "/orders" with body:
      """
      {
        "cartId": "00000000-0000-4000-8000-000000000101",
        "customerId": "00000000-0000-4000-8000-000000000201",
        "email": "shopper@example.com",
        "shippingAddress": "123 Example Street"
      }
      """
    Then the response status is 201
    And the response body has "$.orderNumber" equal to "ORD-2026-000123"
    And the response body has "$.items[0].name" equal to "Widget"

  @status-422 @ac-2
  Scenario: returns 422 when the cart is empty
    Given a cart exists with id "00000000-0000-4000-8000-000000000102" and no items
    When I send a POST request to "/orders" with body:
      """
      {
        "cartId": "00000000-0000-4000-8000-000000000102",
        "customerId": "00000000-0000-4000-8000-000000000202",
        "email": "shopper@example.com",
        "shippingAddress": "123 Example Street"
      }
      """
    Then the response status is 422
    And the error code is "CART_EMPTY"
