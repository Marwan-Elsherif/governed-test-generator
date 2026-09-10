# Storefront page registry

Every page a shopper can reach, and every element a test is allowed to refer to
by name. Element names in this file are the vocabulary for `ui` feature files:
a step that quotes `"Add to cart button"` means the element listed below, on the
page named in the scenario's context.

Names are stable and are not selectors. How an element is found (test id, role,
label) is a step-definition concern and deliberately not specified here, so that
feature files survive a front-end rewrite.

## Product Listing

- **Route:** `/products`
- **Purpose:** Browse the catalogue. The landing page for shoppers arriving at the shop.

| Element | Kind | Label or text |
|---|---|---|
| Sort control | select | "Sort by" |
| Product grid | region | — |
| Product card | article | — |
| Product name | link | product name |
| Product price | text | e.g. "19.99" |
| Add to cart button | button | "Add to cart" |
| Pagination control | nav | "Previous" / "Next" |
| Empty results message | text | "No products match your selection." |

## Product Detail

- **Route:** `/products/{id}`
- **Purpose:** Everything about one product, and the main place a shopper adds to the cart.

| Element | Kind | Label or text |
|---|---|---|
| Product name | heading | product name |
| Product price | text | e.g. "19.99" |
| Product description | text | — |
| Quantity selector | number input | "Quantity" |
| Add to cart button | button | "Add to cart" |
| Back to listing link | link | "Back to products" |

## Cart

- **Route:** `/cart`
- **Purpose:** Review and adjust what will be ordered, then proceed to checkout.

| Element | Kind | Label or text |
|---|---|---|
| Cart line item | row | — |
| Line quantity input | number input | — |
| Remove item button | button | "Remove" |
| Cart subtotal | text | "Subtotal" |
| Cart tax | text | "VAT (21 %)" |
| Cart total | text | "Total" |
| Checkout button | button | "Checkout" |
| Empty cart message | text | "Your cart is empty." |

## Checkout

- **Route:** `/checkout`
- **Purpose:** Collect the details needed to place the order, and place it.

| Element | Kind | Label or text |
|---|---|---|
| Order summary | region | — |
| Customer email field | email input | "Email" |
| Shipping address field | textarea | "Shipping address" |
| Place order button | button | "Place order" |
| Error banner | alert | — |
| Back to cart link | link | "Back to cart" |

## Order Confirmation

- **Route:** `/checkout/confirmation`
- **Purpose:** Confirm to the shopper that the order was placed.

| Element | Kind | Label or text |
|---|---|---|
| Thank-you heading | heading | "Thank you for your order" |
| Continue shopping link | link | "Continue shopping" |
