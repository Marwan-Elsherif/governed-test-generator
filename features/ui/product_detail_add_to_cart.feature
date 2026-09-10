@ui @exemplar
Feature: UI - Product Detail - Add a product to the cart
  As a shopper
  I want to add a product to my cart from its detail page
  So that I can buy it without searching for it again

  Background:
    Given I am on the "Product Detail" page

  @happy-path @smoke @ac-1
  Scenario: Shopper adds a product with the default quantity
    When I click the "Add to cart button"
    Then I should see the text "Added to your cart"
    And I should be on the "Product Detail" page

  @happy-path @ac-2
  Scenario: Shopper adds three of a product
    When I enter "3" in the "Quantity selector"
    And I click the "Add to cart button"
    Then I should see the text "Added to your cart"

  @negative @ac-3
  Scenario: Shopper cannot add a zero quantity
    When I enter "0" in the "Quantity selector"
    And I click the "Add to cart button"
    Then I should see the text "Quantity must be at least 1"
    And I should not see the text "Added to your cart"

  @happy-path @ac-4
  Scenario: Shopper returns to the listing
    When I click the "Back to listing link"
    Then I should be on the "Product Listing" page
    And the URL should contain "/products"
