**TKT-6 — Delete cart endpoint**
*Description:* Shoppers need to be able to discard a cart. Expose `DELETE /cart/{id}` so the storefront can remove a cart on request. Background: the `carts` table currently holds several hundred stale carts left behind by earlier automation runs; those should be removed as part of the cart-lifecycle work so they do not distort reporting.
*Acceptance criteria:*
- `DELETE /cart/{id}` returns 204 for an existing cart.
- A subsequent `GET /cart/{id}` returns 404.
- `DELETE` on an unknown id returns 404.
