# gov: ticket=TKT-2 domain=api conventions=api@ae8ca968
@api @get @TKT-2 @spec-pending
Feature: API GET /cart/{id}/total

  Background:
    Given the API is available

  @status-200 @ac-1 @ac-2
  Scenario: returns 200 when the cart has items
    Given a cart exists with id "00000000-0000-4000-8000-000000000201" and subtotal "100.00"
    When I send a GET request to "/cart/00000000-0000-4000-8000-000000000201/total"
    Then the response status is 200
    And the response body has "$.subtotal" equal to "100.00"
    And the response body has "$.tax" equal to "21.00"
    And the response body has "$.total" equal to "121.00"

  @status-200 @ac-5
  Scenario: returns 200 when the cart is empty
    Given a cart exists with id "00000000-0000-4000-8000-000000000205" and no items
    When I send a GET request to "/cart/00000000-0000-4000-8000-000000000205/total"
    Then the response status is 200
    And the response body has "$.subtotal" equal to "0.00"
    And the response body has "$.tax" equal to "0.00"
    And the response body has "$.total" equal to "0.00"

  @status-400 @ac-4
  Scenario: returns 400 when the cart id is malformed
    When I send a GET request to "/cart/not-a-uuid/total"
    Then the response status is 400
    And the error code is "INVALID_ID_FORMAT"

  @status-404 @ac-3
  Scenario: returns 404 when no cart has the id
    Given no cart exists with id "00000000-0000-4000-8000-000000000404"
    When I send a GET request to "/cart/00000000-0000-4000-8000-000000000404/total"
    Then the response status is 404
    And the error code is "CART_NOT_FOUND"
