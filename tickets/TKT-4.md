---
id: TKT-4
title: Checkout confirmation
---

*Transcribed verbatim from the challenge brief. Acceptance criteria are
numbered here (wording unchanged) to support `@ac-N` traceability in
generated feature files.*

## Description

After the shopper submits checkout, the confirmation page must show the
order number returned by `POST /orders`.

## Acceptance Criteria

1. `POST /orders` with a valid cart returns 201 and an `orderNumber`.
2. `POST /orders` with an empty cart returns 422 and no order is created.
3. The confirmation page displays the returned `orderNumber` and the ordered items.
4. If order creation fails, the shopper stays on the checkout page and sees an error message.
