# ui conventions

Version 1. Applies to `features/ui/**`, together with `conventions/common.md`.
Rule IDs are checked mechanically by `python3 tools/gov.py validate`; a rule
is FAIL unless marked WARN. Worked example: `features/ui/product_detail_add_to_cart.feature`.

## What a ui feature file is

A user journey. Every step is something a shopper does or sees, written in the
shopper's words. It never mentions how the storefront is built or what happens
behind it: no requests, no status codes, no tables. If a behaviour cannot be
observed by a person looking at the screen or the address bar, it does not
belong in a ui feature.

The vocabulary for pages and elements is `shop/ui/pages.md`. Behaviours that
already hold, such as in-page updates and the URL reflecting the view, are in
`shop/ui/journeys.md`.

## Rules

- **UI-01 Title.** `Feature: UI - <Page> - <capability>`, where `<Page>` is a
  page name from the registry, spelled exactly, and `<capability>` is a short
  noun phrase.
- **UI-02 User story.** The three lines directly under the feature line are
  `As a shopper`, `I want <goal>`, `So that <benefit>`, in that order.
- **UI-03 Background.** A `Background:` exists and its first step is
  `Given I am on the "<Page>" page`, naming the same page as the title.
- **UI-04 Scenario names.** Every scenario name starts with `Shopper ` followed
  by a verb phrase: `Scenario: Shopper filters by category`.
- **UI-05 Scenario tags.** Every scenario carries exactly one of `@happy-path`
  or `@negative`. At least one scenario in the feature carries `@smoke`.
- **UI-06 Interactions.** Every `When` step (and `And`/`But` continuing a
  `When`) starts with `I ` and one of these verbs: `click`, `select`, `enter`,
  `clear`, `choose`, `submit`, `open`, `remove`, `set`, `type`, `navigate to`.
  Elements are referred to as `the "<Element>"` and pages as `the "<Page>" page`.
- **UI-07 Assertions.** Every `Then` step (and `And`/`But` continuing a `Then`)
  starts with one of: `I should see`, `I should not see`, `I should be on the
  "<Page>" page`, `the URL should contain`, `the URL should not contain`,
  `the page should not reload`.
- **UI-08 Names.** Every `the "<Page>" page` names a page in the registry.
  Every `the "<Element>"` names an element listed for the page the scenario is
  on, unless the feature is `@spec-pending` (C-07). Free text is written as
  `the text "..."` and is not checked against the registry.
- **UI-09 Forbidden terms.** `http`, `status code`, `endpoint`, `json`, `sql`,
  `table`, `row`, `rows`, `insert`, `migration`, `constraint`,
  `index`, `database`, `xpath`, `css`, `200`, `201`, `204`, `400`, `404`,
  `422`, `500`. The words URL, reload and query are not forbidden: a shopper
  can see them.

## Target state (C-07 for ui)

"The specification" is the page registry. "The thing under test" is the set
of element names the feature refers to. If any of them is not listed for its
page, the feature is `@spec-pending`. The run summary names the new elements.

## Writing it well

Set up state in the shopper's terms (`Given the cart contains 2 items`), not
in the system's. One journey per scenario; if a scenario needs a second
`When`, it is usually two scenarios. Assert what the shopper sees at the end,
not every intermediate state.
