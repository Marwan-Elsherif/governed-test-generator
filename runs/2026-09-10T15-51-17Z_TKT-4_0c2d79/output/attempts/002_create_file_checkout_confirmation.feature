# gov: ticket=TKT-4 domain=ui conventions=ui@3f9a4194
@ui @TKT-4
Feature: UI - Checkout - Confirmation
  As a shopper
  I want to see my order confirmation after checkout
  So that I know my order was placed and what I bought

  Background:
    Given I am on the "Checkout" page

  @happy-path @smoke @ac-3
  Scenario: Shopper sees the returned order number and items on confirmation
    When I submit the checkout form with the order number "ORD-2026-000123"
    And I see the ordered items list
    Then I should be on the "Order Confirmation" page
    And I should see the text "ORD-2026-000123"
    And I should see the text "Widget"

  @negative @ac-4
  Scenario: Shopper stays on checkout when order creation fails
    When I submit the checkout form and the order fails
    Then I should be on the "Checkout" page
    And I should see the text "Unable to place your order"
