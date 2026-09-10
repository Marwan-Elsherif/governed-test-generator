@api @get @exemplar
Feature: API GET /products/{id}

  Background:
    Given the API is available

  @status-200 @ac-1
  Scenario: returns 200 when the product exists
    Given a product exists with id "00000000-0000-4000-8000-000000000101" and price "19.99"
    When I send a GET request to "/products/00000000-0000-4000-8000-000000000101"
    Then the response status is 200
    And the response body has "$.id" equal to "00000000-0000-4000-8000-000000000101"
    And the response body has "$.price" equal to "19.99"

  @status-400 @ac-2
  Scenario: returns 400 when the id is not a UUID
    When I send a GET request to "/products/not-a-uuid"
    Then the response status is 400
    And the error code is "INVALID_ID_FORMAT"

  @status-404 @ac-3
  Scenario: returns 404 when no product has the id
    Given no product exists with id "00000000-0000-4000-8000-000000000404"
    When I send a GET request to "/products/00000000-0000-4000-8000-000000000404"
    Then the response status is 404
    And the error code is "PRODUCT_NOT_FOUND"
