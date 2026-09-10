# gov: ticket=TKT-5 domain=api conventions=api@a89c22c3
@api @get @TKT-5
Feature: API GET /orders

  Background:
    Given the API is available

  @status-200 @ac-3
  Scenario: returns 200 with the default page size
    Given a customer exists with id "00000000-0000-4000-8000-000000000101"
    When I send a GET request to "/orders?customer=00000000-0000-4000-8000-000000000101"
    Then the response status is 200
    And the response body has "$.page" equal to 1
    And the response body has "$.pageSize" equal to 20
    And the response body has "$.items" equal to []

  @status-200 @ac-3
  Scenario: returns 200 with an empty page beyond the last page
    Given a customer exists with id "00000000-0000-4000-8000-000000000102"
    When I send a GET request to "/orders?customer=00000000-0000-4000-8000-000000000102&page=999&pageSize=20"
    Then the response status is 200
    And the response body has "$.items" equal to []
    And the response body has "$.page" equal to 999
    And the response body has "$.pageSize" equal to 20

  @status-200 @nfr @ac-2 @ac-4
  Scenario: returns 200 with the same results for a large customer history under the time budget
    Given a customer has 10000 orders with id "00000000-0000-4000-8000-000000000103"
    When I send a GET request to "/orders?customer=00000000-0000-4000-8000-000000000103&page=1&pageSize=20"
    Then the response status is 200
    And the response body has "$.page" equal to 1
    And the response body has "$.pageSize" equal to 20
    And the response body has "$.totalItems" equal to 10000
    And the response time is under 500 ms
