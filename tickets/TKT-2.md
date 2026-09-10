**TKT-2 — Cart total endpoint**
*Description:* Expose `GET /cart/{id}/total` so the storefront can show totals without fetching the whole cart.
*Acceptance criteria:*
- Returns 200 with `subtotal`, `tax` and `total` for an existing cart.
- `total` equals `subtotal + tax`; tax is calculated at 21 %.
- Returns 404 for an unknown cart id.
- Returns 400 for a malformed cart id.
- An empty cart returns all three values as 0.
