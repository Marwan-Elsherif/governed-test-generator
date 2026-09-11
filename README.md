# Governed test generation

A GitHub Copilot (VS Code) setup that turns a ticket into Gherkin `.feature` files under governance. The agent decides which of three domains (`ui`, `api`, `db`) the ticket concerns, receives **only** those domains' conventions, may write **only** under those domains' folders, and leaves a structured audit a reviewer can check without re-running anything. Enforcement is deterministic Python (a tool-call hook plus a git scope check), not prompt wording.

- **Design, evidence, scaling:** [WRITEUP.md](WRITEUP.md) (two pages).
- **Run records:** [runs/INDEX.md](runs/INDEX.md); one folder per run under `runs/`, including the run that failed.
- **Generated features:** `features/<domain>/`. Three files tagged `@exemplar` were hand-written as worked examples; the other eight were produced by the runs.

## Repository map

| Path | What it is | During a run the agent may |
|---|---|---|
| `tickets/TKT-1.md` … `TKT-6.md` | The six tickets, verbatim from the brief | read |
| `shop/` | The imaginary shop: pages and elements, `openapi.yaml`, error codes, `schema.sql`, migrations | read (the CLI points it at the relevant files) |
| `conventions/common.md`, `ui.md`, `api.md`, `db.md` | The conventions; every rule has an ID (C-01…C-09, UI-01…09, API-01…13, DB-01…10) | **not read directly**; the CLI serves the declared domains' text |
| `features/<domain>/` | Feature files. `steps/` folders are empty placeholders for Behave step definitions (bonus not built) | write, declared domains only; other domains' files are not even readable |
| `policy.json` | The policy as data: write scope per domain, protected paths, read denials, denied tools, terminal allowlist, trusted signing keys | nothing |
| `tools/gov.py`, `tools/govlib/` | Governance CLI and hook entry point, standard library only | run `declare`, `load`, `validate`, `finish`, `status` |
| `tools/tests/`, `tools/simulate_run.py` | 358 tests; a simulator that drives the real hook entry point with synthetic VS Code payloads (59 checks) | nothing |
| `.github/agents/feature-author.agent.md` | The custom agent: workflow, hard rules, summary format | — |
| `.github/prompts/run-ticket.prompt.md` | The `/run-ticket` command; it selects the agent | — |
| `.github/hooks/governance.json` | Every agent lifecycle event goes to `python3 tools/gov.py hook` | — |
| `.github/copilot-instructions.md` | The one always-on instruction channel, kept to two neutral sentences (which agent to use; governance paths are not edited in chat) | — |
| `.vscode/settings.json` | Auto-approval for the two allowed actions; implicit instruction channels switched off | — |
| `schemas/audit.schema.json` | The audit record format; every audit is validated against it at `finish` | nothing |
| `eval/expected_domains.json` | Expected domains per ticket, used only to grade the classification in the audit | nothing |
| `runs/` | One folder per run. `runs/_preflight/` holds the pre-Copilot preflight (Claude Code, two models) | nothing |
| `MANIFEST.json` | Signed hash manifest of the governance bundle (distribution bonus) | nothing |

Not shipped: `docs/PLAN.md`, the author's working plan, which a few code comments still cite; `technical_challenge 4.md`, Avenga's assignment brief, kept out of this public repo but still named as a protected, unwritable path in `policy.json` and exercised by path string in the test suite.

## Prerequisites

- **VS Code with GitHub Copilot Chat**, agent mode, and agent hooks (a Preview feature). Tested on VS Code 1.136.2 with Copilot Chat 0.64.1 on the **Copilot Free** plan, model picker on *Auto*. No extra setting was needed to enable hooks on that version.
- **Python 3** on `PATH` as `python3`. Tested on 3.14.5; the CLI and the simulator also run on 3.11. Nothing to install: `tools/gov.py` uses the standard library only, so it can be vendored into any repository.
- **git**. A run snapshots the working tree at start and diffs against it at finish.
- Optional, for development: `python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt` installs `pytest` and `cryptography`. Without `cryptography` the manifest signature cannot be checked: `verify` reports `unsigned` instead of `ok`, and every run's verdict is downgraded from PASS to REVIEW with that reason (hashes prove consistency, not provenance).
- Developed and run on macOS. The hook file carries `osx` and `linux` commands; Windows is untested.

## Run a ticket

1. Open the folder in VS Code and **trust the workspace**. Workspace settings and hooks apply only in a trusted workspace.
2. Open Copilot Chat in **Agent** mode and type `/run-ticket TKT-2`. The prompt selects the `feature-author` agent; picking that agent in the agent picker and typing the ticket id does the same.
3. What you will see, in order: the agent reads the ticket → runs `python3 tools/gov.py declare --ticket TKT-2 --domains api --rationale … --evidence …` → the terminal result is the only copy of the conventions it gets, plus a worked example, a context pack of `shop/` files, the acceptance criteria numbered for `@ac-<n>` tags, and a skeleton whose first line is the required header → it reads the `shop/` files it needs → creates one file per declared domain → runs `validate` until every rule passes → runs `finish`, which prints the verdict → replies with a fixed `RUN SUMMARY` block.
4. Afterwards, from a terminal:
   - `python3 tools/gov.py annotate --model "<the model the picker showed>"` records the model, which no hook can observe.
   - `python3 tools/gov.py report` refreshes `runs/INDEX.md` (`annotate` does this too).

Cost: about 1.1 premium credits per run on the Free plan where the picker reported it. `chat.agent.maxRequests` is set to 40; a normal run uses 8 to 16 tool calls.

Only two things are auto-approved by `.vscode/settings.json`: the governance CLI in the terminal, and edits under `features/`. The hook decides every tool call before it runs; a denied call is logged in the run and the agent is told why. The agent file instructs it to report denials, not work around them.

**Re-running a ticket that already has output.** Nothing stops it, but the run then *modifies* the existing file rather than creating one, and the audit says so. For a clean run, remove the file first and commit, so the run starts from a clean tree:

```sh
git rm features/api/cart_total_get.feature && git commit -m "Reset TKT-2 for a fresh run"
```

**If a run is left open** (VS Code closed mid-run): `python3 tools/gov.py status` shows it; `python3 tools/gov.py finish --note "closed by hand"` writes its audit. In a normal session the Stop hook does this automatically, so a run that went wrong still leaves a record.

## Run a ticket of your own

```sh
python3 tools/gov.py new-ticket TKT-7 \
  --title "Wishlist" \
  --description "Shoppers can save a product to a wishlist from the product detail page." \
  --ac "The product detail page has an Add to wishlist button." \
  --ac "GET /wishlist returns the saved products for the customer." \
  --expect ui,api --rationale "a page element and an endpoint"
```

This writes `tickets/TKT-7.md` in the same format as the brief's tickets and, with `--expect`, records the expected domains in `eval/expected_domains.json` so the audit can grade the classification (`match: exact | superset | subset | mismatch`). Without `--expect` the audit reports `match: unknown` and the verdict is REVIEW. Then `/run-ticket TKT-7` in Copilot Chat.

## What a run leaves behind

```
runs/2026-09-10T15-51-17Z_TKT-4_0c2d79/
├── audit.md               the record for humans
├── audit.json             the same record, validated against schemas/audit.schema.json
├── events.jsonl           every hook event and every allow/deny decision, in order
├── served/                the exact conventions text the CLI served (+ served.txt log)
├── output/                the final feature file(s) and output/attempts/, every version validated
├── git/diff.patch, status.txt   what changed versus the tree at run start
├── transcript.raw.jsonl   the Copilot chat transcript, attached by the Stop hook
└── manifest.json          run state (who created the run, when it was declared, finished)
```

The run folder is created when the prompt is submitted, before the agent does anything, so even a run that never declares a classification leaves a record (see the failed TKT-6 run).

`audit.json` has the same fields for every run: `ticket`, `session` (agent file hash, model, client versions), `classification` (declared, expected, match, rationale, evidence, `mentioned_not_in_scope`), `conventions` (served files with sha256 and fingerprint, direct reads denied, leak scan), `policy` (allowed write globs, tool calls allowed/denied, attempted violations, terminal commands), `outputs` (per file: validation result, `@ac` coverage, what it adds to the specification), `validation` (every attempt, and the cross-check against the other domains' rules), `git` (changed files, in or out of scope, patch), `governance` (hooks active, policy hash, bundle integrity), `artifacts`, `notes`, `verdict`.

**Verdict.** `FAIL` if any out-of-scope change reached the tree, a final validation failed, the bundle is tampered, or no classification was declared. `REVIEW` if the classification is not an exact match, a validation warning is open, or the bundle signature could not be verified. Otherwise `PASS`. `policy_held` is reported separately: the failed TKT-6 run is `FAIL` with `policy_held: yes`, because nothing out of scope happened, the run just did not complete.

## Reading the evidence for a ticket

Open `runs/<id>/audit.md` and check, in this order:

1. **Conventions in play.** The served table lists exactly the documents the CLI served, with sha256 and an 8-character fingerprint. Compare with line 1 of the output file, e.g. `# gov: ticket=TKT-4 domain=api conventions=api@a89c22c3`: the fingerprint exists in no file the agent can read, so a matching header is evidence the served text was in context (rule C-02). `direct reads of conventions denied` and the leak scan (read contents scanned for other domains' markers) should both be 0 hits.
2. **Policy.** Allowed write paths, tool calls allowed and denied, and the table of attempted violations with the reason each was denied.
3. **Git scope check.** The authoritative answer: files changed since the run's baseline, each marked in or out of scope. It does not depend on the hooks.
4. **Classification.** Declared versus expected, the agent's rationale and the ticket quotes it gave. TKT-6 is the deliberate trap: the description mentions stale `carts` rows, the criteria are API-only; the agent declared `api` and recorded `db` under `mentioned_not_in_scope`.
5. **Outputs and validation history.** Rule failures per attempt, `@ac-<n>` coverage per criterion, and the cross-check showing each output fails the other two domains' rule sets.

Two records worth reading first: `runs/2026-09-10T14-59-00Z_TKT-6_06cda0/` (the failed run: the terminal allowlist rejected a semicolon inside the agent's quoted rationale; the agent reported the denial and finished cleanly; the Notes section holds the root cause) and `runs/_preflight/REPORT.md` (what two Claude models did with the same agent file before any Copilot credits were spent, including one that reported a run it never completed).

## How enforcement works

- **Hooks.** `.github/hooks/governance.json` sends every lifecycle event (session start, prompt, before and after each tool call, subagent start/stop, stop) to `python3 tools/gov.py hook`. On `PreToolUse` the hook decides as a pure function of (tool, input, run state, `policy.json`): writes only under the declared domains' feature folders, governance paths never writable, only the CLI in the terminal (allowlist regex), search, web and subagent tools denied, unknown tools carrying paths denied. On an internal error it denies anything write-like, because VS Code treats a crashed hook as "allow".
- **Conventions are served, never read.** `declare` and `load` are the only paths to the conventions; each serving is logged with hash and fingerprint. Implicit channels are off: no `applyTo` instruction files (VS Code attaches those by glob *or semantic match*), no skills, no `AGENTS.md`, no search tools.
- **Git scope check at `finish`.** Every change since the baseline is classified in or out of scope. This works with hooks off and is what the verdict trusts.
- **The audit is written by the harness**, from what it observed. The model's own summary appears nowhere in it.
- **`policy.json` is the file a team edits** to map its own layout onto the domains. The rules themselves are code in `tools/govlib/rules*.py`; a test checks that every rule ID in the code appears in the conventions and vice versa.

## Verify the tooling without Copilot

```sh
python3 -m pytest                       # 358 tests, ~20 s
python3 tools/simulate_run.py           # 59 checks through the real hook entry point, in a temporary copy
python3 tools/simulate_run.py --keep    # same, keeping the copy at runs/_simulation_last/
python3 tools/gov.py validate --ticket TKT-3 features/db/order_items_order_items_quantity_constraint.feature
python3 tools/gov.py verify             # bundle integrity: ok | unsigned | tampered | not_configured
```

The simulator plays a whole synthetic session through the real entry point — a declare, a failing then a passing file, and 14 calls that must be denied: writes outside scope and to protected paths, direct convention and answer-key reads, a workspace search, arbitrary and destructive shell commands, an unknown tool carrying a path — and checks the resulting audit (12 of the 14 count as attempted violations; the other two are denied searches).

If you edit any file in the governance bundle (conventions, `policy.json`, the CLI, the Copilot wiring) without re-sealing, `verify` reports `tampered`, `declare` refuses to start a run, and the four tests that play a whole session fail with a FAIL verdict for the same reason. `python3 tools/gov.py seal --version <next>` clears it; that needs the signing key, or `--unsigned` for a local experiment.

`validate` outside a run checks a file against **today's** conventions. Rule C-02 pins the conventions version, so an output generated under an earlier version fails C-02 on purpose: `features/api/cart_total_get.feature` (TKT-2) and `features/api/cart_delete.feature` (TKT-6) carry `api@ae8ca968`, the `api.md` in force before rule API-13 was added; today's is `api@a89c22c3`. Every other rule still passes on both files, and their audits hold the validation record against the version that was served. `cart_delete.feature` also carries the API-13 warning that rule was written to catch (a scenario for "a subsequent GET returns 404" that sends a DELETE), left in place as evidence.

## Integrity and distribution (bonus)

`MANIFEST.json` holds sha256 hashes of the governance bundle (conventions, `policy.json`, schema, CLI, Copilot wiring; 30 files) and an Ed25519 signature. The private key never enters the repository (default path `~/.governed-test-gen/signing_key.hex`); the trusted public key is in `policy.json`.

```sh
python3 tools/gov.py verify [--strict]          # --strict treats unsigned/untrusted as tampered; for CI
python3 tools/gov.py keygen                     # one-time, per maintainer
python3 tools/gov.py seal --version 1.0.3       # after any change to governance files
python3 tools/gov.py bundle --out dist          # dist/governed-test-generation-<version>.tar.gz + LATEST.json
python3 tools/gov.py install --bundle dist/governed-test-generation-<version>.tar.gz --target ../other-repo --trust-key <hex>
python3 tools/gov.py update --latest <path to a published LATEST.json>   # reports whether a newer bundle exists; never writes (a file read here, an HTTPS GET in a real deployment)
```

What it does under attack: edit `conventions/api.md` and `verify` names the file and `declare` refuses to serve anything (exit 2), so no run can start on tampered conventions; re-seal without the key and `--strict` rejects the unsigned manifest; re-seal with a different key and it is rejected as untrusted; `install` verifies the staged bundle against the trusted key before writing a single file. The honest boundary, and how it scales to many repositories, is in [WRITEUP.md](WRITEUP.md) §3. Every audit records the bundle's integrity state at the time of the run.

## Bonus items

| Bonus | Status |
|---|---|
| Deterministic policy enforcement | Built: hook + git scope check + harness-written audit |
| Distribution with tamper detection | Built: signed manifest, `verify`/`seal`/`bundle`/`install`/`update` |
| Jira as ticket source via MCP | Not built |
| Behave step-definition skeletons | Not built (`features/<domain>/steps/` are placeholders) |

## Known limitations

- Agent hooks are a Preview feature: matchers are ignored, tool names are not documented, a crashed hook means "allow". The design assumes all three (single fail-closed entry point; git check as the backstop that needs no hooks).
- No hook exposes the model in use; it is recorded by hand with `annotate --model`. Only the first live run has it recorded.
- `@ac-<n>` tags prove traceability, not that a compound criterion was fully exercised; three such gaps are named in the write-up.
- The manifest and its verifier live in the repository they protect; local `verify` is fast feedback, CI with `--strict` from a trusted checkout is the control.
