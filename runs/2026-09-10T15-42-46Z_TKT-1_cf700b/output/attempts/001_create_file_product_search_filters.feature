# gov: ticket=TKT-1 domain=ui conventions=ui@3f9a4194
@ui @TKT-1 @spec-pending
Feature: UI - Product Listing - Search filters
  As a shopper
  I want to filter products by category and price range
  So that I can find the right items quickly

  Background:
    Given I am on the "Product Listing" page

  @happy-path @smoke @ac-1
  Scenario: Shopper filters products by category
    When I select "Home & Garden" in the "Category filter"
    Then I should see only products in the "Home & Garden" category

  @happy-path @ac-2
  Scenario: Shopper filters products by price range
    When I enter "10.00" in the "Minimum price field"
    And I enter "25.00" in the "Maximum price field"
    Then I should see only products priced between "10.00" and "25.00"

  @happy-path @ac-3
  Scenario: Shopper combines category and price filters
    When I select "Kitchen" in the "Category filter"
    And I enter "15.00" in the "Minimum price field"
    And I enter "40.00" in the "Maximum price field"
    Then I should see only products in the "Kitchen" category priced between "15.00" and "40.00"

  @negative @ac-4
  Scenario: Shopper applies filters without reloading the page
    When I select "Books" in the "Category filter"
    Then the URL should contain "category="
    And the page should not reload

  @happy-path @ac-5
  Scenario: Shopper clears the filters
    When I select "Games" in the "Category filter"
    And I clear the "Category filter"
    And I clear the "Minimum price field"
    And I clear the "Maximum price field"
    Then I should see the full listing
