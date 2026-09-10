# Web shop — system under test

This directory specifies the fictional web shop that test scenarios are written
against. There is no running application and none is expected: these documents
are the source of truth. A `.feature` file is correct when it matches what is
specified here, not when it passes against a server.

The shop is split into three domains, which is also how test ownership is split:

| Domain | What it covers | Specified in |
|---|---|---|
| `ui` | The storefront a shopper uses: listing, detail, cart, checkout, confirmation | `shop/ui/` |
| `api` | The REST backend the storefront calls | `shop/api/` |
| `db` | The relational store behind the API | `shop/db/` |

## Facts that hold everywhere

These are referenced by all three domains. Where a ticket and this document
disagree, this document wins, and the discrepancy is worth noting in the run's
audit record rather than silently resolving.

**Identifiers.** Products, carts, cart items, orders, order items and customers
are identified by UUID v4, lowercase and hyphenated, for example
`3f2a7c18-9b4e-4d21-a5f6-0c8e1b2d3a44`. An identifier that is not a well-formed
UUID is a client error rather than a lookup miss: the API answers `400`, never
`404`. A well-formed UUID that matches no row answers `404`.

**Order numbers.** An order carries both a UUID (`id`, used in URLs) and a
human-facing order number (`orderNumber`) of the form `ORD-<year>-<six digits>`,
for example `ORD-2026-000123`. The sequence restarts each calendar year. Order
numbers are what a shopper is shown and quotes to support; UUIDs are not.

**Money.** Stored in the database as integer cents (`price_cents`,
`subtotal_cents`, and so on) to avoid floating-point drift. Exposed by the API
as a JSON **string** with exactly two decimal places: `"19.99"`. Zero is
`"0.00"`, never `0` or `"0"`. Currency is EUR throughout; there is no
multi-currency support and no currency field.

**Tax.** A single VAT rate of 21 % applies to every product. Prices shown in the
storefront and stored on products are **excluding** tax. Tax is calculated on
the order subtotal, not per line, and rounded half-up to the nearest cent.
So `total = subtotal + tax`, where `tax = round_half_up(subtotal * 0.21)`.

**Timestamps.** RFC 3339 in UTC with a trailing `Z`, for example
`2026-09-10T14:23:05Z`.

**Test data.** Rows created by automated tests use identifiers from the reserved
UUID range `00000000-0000-4000-8000-XXXXXXXXXXXX`, where the final block is free
for the test to choose. Nothing outside automated testing ever writes an
identifier in that range, so a cleanup can safely delete by prefix. Tests are
responsible for removing the rows they create; see `shop/db/README.md`.

## How the three layers fit together

The storefront never talks to the database. Every storefront action is one or
more API calls, and the API owns all persistence. A consequence worth keeping in
mind when writing tests: a UI-level expectation such as "no order was created"
is observed through the API (a subsequent request returns `404`), not by
counting rows.
