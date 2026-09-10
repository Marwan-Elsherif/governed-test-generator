# gov: ticket=TKT-6 domain=api conventions=api@ae8ca968
@api @delete @TKT-6 @spec-pending
Feature: API DELETE /cart/{id}

  Background:
    Given the API is available

  @status-204 @ac-1
  Scenario: returns 204 when the cart exists
    Given a cart exists with id "00000000-0000-4000-8000-000000000101"
    When I send a DELETE request to "/cart/00000000-0000-4000-8000-000000000101"
    Then the response status is 204
    And the response body is empty

  @status-404 @ac-2
  Scenario: returns 404 when the cart was deleted
    Given a cart was deleted with id "00000000-0000-4000-8000-000000000202"
    When I send a GET request to "/cart/00000000-0000-4000-8000-000000000202"
    Then the response status is 404
    And the error code is "CART_NOT_FOUND"

  @status-404 @ac-3
  Scenario: returns 404 when the cart does not exist
    Given no cart exists with id "00000000-0000-4000-8000-000000000404"
    When I send a DELETE request to "/cart/00000000-0000-4000-8000-000000000404"
    Then the response status is 404
    And the error code is "CART_NOT_FOUND"
