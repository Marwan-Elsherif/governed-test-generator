# API error envelope and codes

Every non-2xx response has the same body shape. Tests assert on the `code`,
never on the `message`: messages are wording and may change without notice,
codes are contract.

```json
{
  "error": {
    "code": "CART_NOT_FOUND",
    "message": "No cart with id 3f2a7c18-9b4e-4d21-a5f6-0c8e1b2d3a44.",
    "details": {}
  }
}
```

`details` is present but may be an empty object. For validation failures it
carries the offending fields, for example
`{"fields": {"quantity": "must be at least 1"}}`.

## Code catalogue

| Code | Status | Raised when |
|---|---|---|
| `INVALID_ID_FORMAT` | 400 | A path or query identifier is not a well-formed UUID. |
| `VALIDATION_FAILED` | 400 | A request body or query parameter failed validation. |
| `PRODUCT_NOT_FOUND` | 404 | No product with the given id. |
| `CART_NOT_FOUND` | 404 | No cart with the given id. |
| `CART_ITEM_NOT_FOUND` | 404 | The cart exists but has no such line. |
| `ORDER_NOT_FOUND` | 404 | No order with the given id. |
| `CART_EMPTY` | 422 | An order was requested for a cart with no items. |
| `CART_NOT_OPEN` | 422 | An order was requested for a cart that is already ordered or abandoned. |
| `PRODUCT_INACTIVE` | 422 | A product exists but is not available to order. |
| `INTERNAL_ERROR` | 500 | Anything unhandled. Never asserted on deliberately. |

## Choosing between 400, 404 and 422

This trips people up often enough to be worth stating plainly.

- **400** means the request could not be understood: a malformed UUID, a
  `pageSize` of `abc`, a body missing a required field. The server did not need
  to look anything up to reject it.
- **404** means the request was well formed and the thing genuinely is not
  there. A well-formed UUID that matches no row is always `404`, never `400`.
- **422** means the request was well formed and the thing exists, but the
  operation is not allowed in the current state. Ordering an empty cart is the
  canonical example: the cart is real, the request is valid, the state is wrong.

## Pagination

Collection endpoints that are paginated take `page` (1-based, default 1) and
`pageSize` (default 20, maximum 100), and answer with an envelope:

```json
{
  "items": [],
  "page": 4,
  "pageSize": 20,
  "totalItems": 61,
  "totalPages": 4
}
```

A page beyond the last is not an error. It answers `200` with an empty `items`
array and the same metadata, so a client paging forward stops naturally rather
than having to handle a failure. A `page` of `0` or a negative `pageSize` is a
`400` with `VALIDATION_FAILED`.

Not every collection endpoint is paginated today. `GET /products` is; check the
spec in `openapi.yaml` before assuming.

## Money in responses

Monetary fields are strings with exactly two decimals, as set out in
`shop/README.md`. `"0.00"` is the representation of zero, including on an empty
cart where subtotal, tax and total are all `"0.00"`.
