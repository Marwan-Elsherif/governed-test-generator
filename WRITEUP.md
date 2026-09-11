# Governed test generation: design, evidence, scaling

## 1. Design

**Shape.** One custom Copilot agent (`feature-author`), one governed CLI (`tools/gov.py`, stdlib-only), one hooks file, and a rule engine. The model does only what only a model can: classify the ticket, with rationale and quotes, and write the scenarios. Everything else is deterministic Python, tested without Copilot (358 tests, 41 rule IDs traceable to sentences in `conventions/`).

**A run.** `/run-ticket TKT-n` opens a run. The agent reads the ticket and runs `gov.py declare` with domains, rationale and quotes. The CLI locks the classification and serves the declared domains' conventions, a worked example, a context pack, and a skeleton whose first line carries a **serve-time fingerprint** (8 hex of its sha256). The agent writes one file per domain, runs `validate` until every rule passes, then `finish`, which writes the audit.

**Why conventions load this way.** The brief asks for "those domains only" and for proof, so every implicit channel is closed: no `applyTo` instruction files (VS Code attaches those by glob *or semantic match*), no skills, no search tools; other domains' examples, run records, the answer key, tooling and notes are denied. Conventions are readable only through `declare`/`load`, which log what they served with hash and fingerprint. The fingerprint exists in no readable file, so a header carrying it is evidence the served text was in context (rule C-02).

**Enforcement, three layers.** A PreToolUse hook decides every tool call as a pure function of (tool, input, run state, `policy.json`): writes only under the declared domains' feature folders, governance paths never writable, only the CLI in the terminal, search and subagent tools denied. It fails closed, since VS Code treats a crashed hook as "allow". Second, `finish` runs a git scope check against the run's baseline: it works with hooks off and is the authoritative answer. Third, read contents are scanned for other domains' markers. An unfinished run is auto-finalized at Stop. The audit is schema-validated and built only from what the harness observed; the model's own account appears nowhere in it.

**Alternatives rejected.** Per-domain subagents: structural isolation, but hook coverage of subagent calls was still being fixed in VS Code (PR #308574), hook input has no agent identifier (#293631), and subagents bill credits. An MCP server as sole write tool: the same guarantee, more infrastructure. Prompt-only rules: not enforcement.

## 2. Evidence

Six tickets, seven live runs (VS Code 1.136.2, Copilot Chat 0.64.1, Copilot Free on auto model; GPT-5.6 Luna at 1.1 credits where I checked the picker); every row verified from `runs/<id>/`, never from the agent's summary.

| Ticket | Declared | Match | Verdict | Calls / denied | Files, scenarios | Served (fingerprint) |
|---|---|---|---|---|---|---|
| TKT-2 | api | exact | PASS | 10 / 1 | 1, 4 | api@ae8ca968 |
| TKT-3 | db | exact | PASS | 12 / 0 | 1, 6 | db@3d7d6a02 |
| TKT-6 #1 | none | undeclared | FAIL | 4 / 1 | 0 | none |
| TKT-6 #2 | api | exact | PASS | 11 / 0 | 1, 3 | api@ae8ca968 |
| TKT-1 | ui | exact | PASS | 8 / 0 | 1, 5 | ui@3f9a4194 |
| TKT-4 | ui, api | exact | PASS | 15 / 0 | 2, 4 | ui@3f9a4194, api@a89c22c3 |
| TKT-5 | db, api | exact | PASS | 16 / 0 | 2, 6 | db@3d7d6a02, api@a89c22c3 |

**Right conventions.** Each audit lists exactly the served documents with sha256 and fingerprint; each output's header matches; no run attempted a direct convention read; every output fails the other two domains' rule sets. **Policy held.** Zero out-of-scope changes in every run, every tool call logged. The hook denying a call in real Copilot is on record twice (a search tool, a terminal command); a denied *write outside the declared domain* exists only in the simulator (`tools/simulate_run.py`, 14 synthetic denials), because no real run attempted one. TKT-6 is the trap: the description mentions stale rows in the `carts` table, the criteria are all API-level. The agent declared `api`, recorded `--mentioned db`, and quoted the bait sentence as its reason for excluding it, with no "scope follows acceptance criteria" rule in the agent file (held back to see whether it was needed).

**What did not work, and how I found out.** Six tooling defects, each found by a real run and fixed with a regression test: `tool_search` (VS Code's tool-catalogue lookup) denied as a codebase search; the terminal allowlist rejecting a semicolon inside a quoted rationale, which blocked a correctly classified TKT-6 (run #1; the agent reported the failure rather than working around it); the ui element regex reading `the "Home & Garden" category` in a Then step as a page element; `annotate` recomputing git facts against a later tree, flipping PASS to FAIL; client versions and the transcript pointer missing because `finish` runs before the Stop hook attaches the transcript; `tools/**` and `docs/**` readable during a run, a leak my scan could not see (the logs show `docs/PLAN.md`, holding the expected answers, was never read).

Three gaps the validator cannot see, found by reading outputs against the tickets: TKT-6's scenario for "a subsequent GET returns 404" sends a DELETE (now warned by API-13); TKT-5's db scenario is tagged for four criteria and tests one; two before/after criteria (TKT-4, TKT-5) are asserted on one side only. Tag-level coverage proves traceability, not that a compound criterion was fully exercised. Agent summaries drift from the record: TKT-2 reported "denied tool calls: 0" against a logged denial; in the preflight (`runs/_preflight/`, Haiku 4.5 and Sonnet 5 in Claude Code) Haiku reported a completed run with no audit behind it. Its content was correct every time; its account of the process was not.

## 3. Scaling to dozens of repositories

Built: a signed manifest (`gov.py seal`, Ed25519 via the optional `cryptography` package; hashes are stdlib), `verify` (`ok`/`unsigned`/`tampered`/`not_configured`), `bundle`/`install`/`update`, and `declare` refusing to serve conventions from a tampered bundle. Exercised: weaken API-06 and `verify` names the file, `declare` exits 2; unsigned re-sealing is caught by `--strict`, a foreign key as untrusted; `install` refuses an unexpected signer.

**Structure.** A central governance repository publishes semver bundles of governance material only: conventions, `policy.json`, schema, tooling, Copilot wiring. Consuming repositories vendor them with `install`, take updates as bot-opened PRs from `update --check`, and map their layout in `policy.json`. Team overlays add rules, never remove mandatory ones; CODEOWNERS covers governance paths; audits carry bundle version and integrity state and go to a central store.

**The honest boundary.** The manifest and the verifier live in the repository they protect, so a determined local actor can edit both; hashes catch drift, the signature catches re-sealing. Local verification is fast feedback; the control is CI running `verify --strict` from a trusted checkout against the organisation's key, preventive versus detective again. Not built: a Jira ticket source, Behave step skeletons.
