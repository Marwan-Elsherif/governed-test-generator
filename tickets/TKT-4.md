**TKT-4 — Checkout confirmation**
*Description:* After the shopper submits checkout, the confirmation page must show the order number returned by `POST /orders`.
*Acceptance criteria:*
- `POST /orders` with a valid cart returns 201 and an `orderNumber`.
- `POST /orders` with an empty cart returns 422 and no order is created.
- The confirmation page displays the returned `orderNumber` and the ordered items.
- If order creation fails, the shopper stays on the checkout page and sees an error message.
