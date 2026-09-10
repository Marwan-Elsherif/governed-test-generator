# api conventions

Version 1. Applies to `features/api/**`, together with `conventions/common.md`.
Rule IDs are checked mechanically by `python3 tools/gov.py validate`; a rule
is FAIL unless marked WARN. Worked example: `features/api/products_get.feature`.

## What an api feature file is

A request/response contract for one endpoint. Every scenario sends exactly one
request and asserts the status code and the body. It says nothing about
screens or storage: no clicks, no tables. Test data is arranged through
fixture steps that describe state ("a cart exists with ..."), never through
SQL or the database vocabulary.

Endpoints, parameters and response shapes are in `shop/api/openapi.yaml`.
The error envelope, the code catalogue and the 400/404/422 rule are in
`shop/api/errors.md`. Identifier, money and tax rules are in `shop/README.md`.

## Rules

- **API-01 Title.** `Feature: API <METHOD> <path>`, with the method in upper
  case and the path template as written in the specification or the ticket,
  for example `Feature: API GET /cart/{id}/total`.
- **API-02 Feature tags.** The feature line carries `@api` and the method in
  lower case as a tag: `@get`, `@post`, `@patch`, `@delete` or `@put`.
- **API-03 Background.** A `Background:` exists and its first step is exactly
  `Given the API is available`.
- **API-04 Status tag.** Every scenario carries exactly one `@status-<code>`
  tag with a three-digit code, and contains the step
  `Then the response status is <code>` with the same code.
- **API-05 One request.** Every scenario contains exactly one step of the form
  `When I send a <METHOD> request to "<path>"`, where `<METHOD>` is the
  feature's method and `<path>` matches the title's path template. A request
  body, if any, is a docstring directly under that step.
- **API-06 Body assertion.** Every scenario contains at least one of
  `And the response body has "<json path>" equal to <value>`,
  `And the response body has "<json path>" matching <regex>`,
  `And the response body is empty`,
  `And the error code is "<CODE>"`. Every scenario with a 4xx status contains
  `And the error code is "<CODE>"` with a code from the catalogue.
- **API-07 Order.** Scenarios appear in ascending status code order: 2xx
  first, then 4xx ascending.
- **API-08 Scenario names.** `returns <code> when <condition>`, where
  `<code>` equals the scenario's status tag.
- **API-09 Money.** Any value asserted for `subtotal`, `tax`, `total`, `price`,
  `unitPrice` or `lineTotal` is a quoted string with exactly two decimals:
  `"19.99"`, `"0.00"`. Never a bare number.
- **API-10 Timing.** A scenario that asserts a response time carries `@nfr`
  and states the data volume in a `Given` step. A scenario tagged `@nfr`
  asserts a response time with `And the response time is under <n> ms`.
- **API-11 Fixtures.** State is arranged with `Given` steps in the form
  `Given a <thing> exists with id "<uuid>" ...` or
  `Given no <thing> exists with id "<uuid>"`. Every identifier literal is from
  the reserved test range `00000000-0000-4000-8000-XXXXXXXXXXXX`.
- **API-12 Forbidden terms.** `click`, `button`, `screen`, `shopper`,
  `i see`, `i should see`, `the page`, `table`, `row`, `rows`, `column`,
  `insert into`, `select *`, `constraint`, `database`, `schema`.

## Target state (C-07 for api)

"The specification" is `openapi.yaml`. "The thing under test" is the title's
method and path. If that operation is not in the specification, the feature
is `@spec-pending` and the contract is derived from the ticket plus the shared
rules in `shop/`. The run summary says which operation is new.

## Writing it well

The happy path first, then each failure by ascending status. Use a
`Scenario Outline` when several inputs share one outcome. Assert the fields
the ticket names, not the whole body.
