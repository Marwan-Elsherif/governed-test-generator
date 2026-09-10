### Assignment: Governed Test-Generation Agents

You'll have two days to work on this before the technical interview. We don't expect you to spend the whole of that time on it — a focused effort is fine, and we would rather see fewer tickets with solid evidence than all six unverified. During the interview you'll demo your solution and we'll discuss the decisions you made. We care far more about **why** you built it the way you did, and **how you know** it behaves the way you claim, than about polish.

**Tooling.** You may use any AI assistant (Claude, ChatGPT, Codex, Gemini, …) to help you build the solution. The agents themselves, and your demo, must run in **GitHub Copilot in VS Code**. A free Copilot plan is sufficient, but plan your testing around its request limits — building with another assistant and reserving Copilot for running the agents is a sensible split. On the free plan, agents will not always behave as intended; that is part of the exercise. You don't need to save every chat — but if a run got partway through correctly and then went wrong (say, a later step ignored what an earlier step had established), keep that transcript and bring it. We would rather see the part that worked and the point where it broke than a cleaned-up version. You may also use any model available to you in Copilot's model picker (including free-tier models from other providers) instead of the default one.

#### The system under test

Imagine a small web shop, split into three domains:

- **ui** — the storefront: product listing, product detail, cart, checkout pages. Tests are user-journey style (navigate, click, assert what the user sees).
- **api** — the REST backend: `/products`, `/cart`, `/orders`. Tests are request/response style (status codes, payload shape, error cases).
- **db** — the relational store behind the API: `products`, `orders`, `order_items`, `carts` tables. Tests are data-integrity style (constraints, migrations, cleanup after test data).

There is no real application and you are not expected to build a working one. You do need a repository that *looks* enough like one for your agents to produce good feature files: page descriptions, endpoint definitions, a schema, existing example tests — whatever context your agents need. Use an AI assistant to generate as much of this scaffolding as you like; the repository can be as large or as small as you judge necessary for the agents to perform well.

#### Your task

Build a Copilot-based setup that, given a ticket, produces a **Gherkin `.feature` file** with test scenarios for that ticket, following domain-specific conventions that **you** define.

Concretely:

1. **Define conventions per domain.** Write instruction material for each of the three domains: naming, structure, mandatory elements, whatever you decide a good `ui` / `api` / `db` feature file must contain. Make them meaningfully different from each other.
2. **Build the agent setup.** Given a ticket, it must:
   - decide which domain(s) the ticket concerns,
   - load the conventions for **those domains only**,
   - produce the feature file(s).
3. **Enforce the policy.** The following rules apply to every run. How you enforce them is up to you.
   - **Scope.** An agent working on a ticket may only create or modify files belonging to the domains that ticket concerns. Anything else is a violation.
   - **Audit.** Every run must leave a record that a human can review afterwards, without re-running anything. The record must follow a consistent, structured format of your choosing — the same format for every run, regardless of which agent produced it.
4. **Prove it.** For each ticket you run, show evidence that exactly the right conventions were in play and the policy held. "The output looks right" is not evidence.

#### Tickets

They are deliberately short and imperfect, like real tickets.

**TKT-1 — Product search filters**
*Description:* As a shopper I can filter the product listing by category and price range. Results update without a full page reload.
*Acceptance criteria:*
- Category filter shows only products in the selected category.
- Price range filter shows only products within the min/max entered.
- Both filters can be combined.
- Applying a filter does not reload the page; the URL reflects the active filters.
- Clearing filters restores the full listing.

**TKT-2 — Cart total endpoint**
*Description:* Expose `GET /cart/{id}/total` so the storefront can show totals without fetching the whole cart.
*Acceptance criteria:*
- Returns 200 with `subtotal`, `tax` and `total` for an existing cart.
- `total` equals `subtotal + tax`; tax is calculated at 21 %.
- Returns 404 for an unknown cart id.
- Returns 400 for a malformed cart id.
- An empty cart returns all three values as 0.

**TKT-3 — Order items quantity constraint**
*Description:* `order_items.quantity` currently accepts any integer. It must be a positive integer.
*Acceptance criteria:*
- Inserting or updating an `order_items` row with quantity ≤ 0 is rejected.
- Existing rows are unaffected by the migration; the migration fails if any existing row would violate the constraint.
- The constraint is reversible (down migration removes it).

**TKT-4 — Checkout confirmation**
*Description:* After the shopper submits checkout, the confirmation page must show the order number returned by `POST /orders`.
*Acceptance criteria:*
- `POST /orders` with a valid cart returns 201 and an `orderNumber`.
- `POST /orders` with an empty cart returns 422 and no order is created.
- The confirmation page displays the returned `orderNumber` and the ordered items.
- If order creation fails, the shopper stays on the checkout page and sees an error message.

**TKT-5 — Order history performance**
*Description:* `GET /orders?customer={id}` is slow for customers with many orders.
*Acceptance criteria:*
- An index exists on `orders.customer_id`.
- The endpoint returns the same results before and after the index is added.
- Results are paginated (`page`, `pageSize`); default page size is 20; pages beyond the last return an empty list with 200.
- Response time for a customer with 10 000 orders is under 500 ms.

**TKT-6 — Delete cart endpoint**
*Description:* Shoppers need to be able to discard a cart. Expose `DELETE /cart/{id}` so the storefront can remove a cart on request. Background: the `carts` table currently holds several hundred stale carts left behind by earlier automation runs; those should be removed as part of the cart-lifecycle work so they do not distort reporting.
*Acceptance criteria:*
- `DELETE /cart/{id}` returns 204 for an existing cart.
- A subsequent `GET /cart/{id}` returns 404.
- `DELETE` on an unknown id returns 404.

#### Deliverables

1. **A repository** (public GitHub, or a zip) containing everything needed to run the setup in VS Code with Copilot, plus a README explaining how.
2. **Generated feature files and their audit records** for as many tickets as you managed to run — ideally all six, at least two. Include transcripts of runs that did not go as planned.
3. **A write-up** (Markdown, no more than 2 pages) covering:
   - Your design: how the setup is structured, how conventions get loaded, how the policy is enforced — and *why* you chose that over the alternatives you considered.
   - Your evidence: how you know the right conventions loaded for each ticket, and how you know the policy held. Include what you tried that **didn't** work and how you found out.
   - Scaling this out: this setup will have to live in dozens of project repositories owned by different teams. Describe how you would structure and distribute it.
4. **A 10-minute live demo** at the interview: run one ticket of our choosing, then walk us through the evidence.

#### Bonus (pick any, none required)

- Enforce the policy deterministically.
- Replace the ticket files with a real ticket source (e.g. Jira via MCP) and post the audit record there.
- Generate step-definition skeletons (Python/Behave) alongside the feature files.
- Implement a minimal version of your distribution design. We need a way to push updates out and to detect local tampering.

Questions before the interview are welcome: stefan.markoski@avenga.com

---