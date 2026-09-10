# gov: ticket=TKT-4 domain=ui conventions=ui@3f9a4194
@ui @TKT-4
Feature: UI - Checkout - Confirmation
  As a shopper
  I want to see my order confirmation after checkout
  So that I know my order was placed and what I bought

  Background:
    Given I am on the "Checkout" page

  @happy-path @smoke @ac-1 @ac-3
  Scenario: Shopper completes checkout and sees the order summary
    When I click the "Place order button"
    Then I should be on the "Order Confirmation" page
    And I should see the text "ORD-2026-000123"
    And I should see the text "Widget"

  @negative @ac-2 @ac-4
  Scenario: Shopper cannot place an order from an empty cart
    Given the cart contains 0 items
    When I click the "Place order button"
    Then I should be on the "Checkout" page
    And I should see the text "Your cart is empty."
