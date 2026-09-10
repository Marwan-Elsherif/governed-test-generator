# Storefront journeys and behaviours

How the pages in `pages.md` connect, and the behaviours a `ui` test can rely on.
Written from the shopper's point of view, because that is how storefront tests
are written: what someone does, and what they then see.

## The main journey

1. A shopper lands on **Product Listing** and browses the catalogue.
2. They open a **Product Detail** page from a product name.
3. They choose a quantity and add the product to the cart.
4. They open the **Cart**, adjust quantities or remove lines.
5. They continue to **Checkout**, enter their email and shipping address.
6. They place the order and arrive at **Order Confirmation**.

A shopper is anonymous until checkout. There is no account, no login and no
saved address; the cart is identified by a cookie holding the cart's UUID.

## Listing behaviour

The listing shows 20 products per page. Sorting and paging are **in-page
updates**: the grid is replaced via a background request, the browser does not
perform a full page load, and nothing outside the grid flickers or resets.

Two rules follow from that, and both are things a test can assert:

- **The URL reflects the current view.** Active sorting and paging appear in the
  query string, for example `/products?sort=price_asc&page=2`. The view is
  therefore shareable, survives a browser refresh, and the browser's back and
  forward buttons move between previous views.
- **The page does not reload.** Any change that only alters which products are
  shown is an in-page update. A full page load is a defect, not an
  implementation detail.

When a view matches no products, the grid is replaced by the **Empty results
message** and the pagination control is hidden.

## Cart behaviour

The cart shows one line per product, with a quantity, a line total, and then the
subtotal, VAT and total from the shared money and tax rules in
`shop/README.md`. Changing a quantity or removing a line updates the totals
in place, on the same principle as the listing.

A quantity of zero is not how a line is removed: the shopper uses the **Remove
item button**. The **Line quantity input** accepts positive whole numbers only.

An empty cart shows the **Empty cart message**, and the **Checkout button** is
not available.

## Checkout behaviour

Checkout shows an **Order summary** of what will be ordered, alongside the fields
the shopper must complete. Validation problems, for example a malformed email
address, are shown in the **Error banner** and the shopper stays on the page with
what they have already typed still in place.

Placing an order is not instantaneous. While the order is being placed the
**Place order button** is disabled, so a shopper cannot submit twice.

## Confirmation behaviour

The confirmation page currently thanks the shopper for the order. It is reached
only by placing an order: navigating to it directly, without having just
completed a checkout, redirects to the **Cart**.
