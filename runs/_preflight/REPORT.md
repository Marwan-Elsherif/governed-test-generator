# Context preflight — step 8

**Question.** Is the context the loader serves (conventions, worked example,
context pack, skeleton) enough for a weak model to write a passing feature
file? This is checked before spending Copilot credits on the real thing.

**Method.** Each of Haiku 4.5 and Sonnet 5 ran the real, unmodified
`.github/agents/feature-author.agent.md` workflow — declare, read, write,
validate, finish — against TKT-2 (api) and TKT-3 (db), each in its own
isolated git worktree so the four runs could not interfere with each other.
Classification was left to the model, not supplied, since both tickets are
low-ambiguity and this is realistic. All four transcripts are preserved
below.

**Two honest limits on how far this generalises**, stated up front rather
than glossed over:

1. These are Claude models in the Claude Code harness, not literally
   Copilot's auto-selected Free-plan model in VS Code. This is a proxy for
   "a smaller/cheaper model's capability", not a simulation of Copilot's
   specific model selection.
2. A general-purpose Claude Code subagent has full tool access; nothing here
   enforces the agent file's read restrictions the way the VS Code hook does.
   So this step tests whether the served *content* is sufficient, not whether
   enforcement holds — that is what `tools/simulate_run.py` (step 6) and the
   step 9 discovery run are for.

## Results

| model | ticket | governed run completed? | content, independently validated | self-report accurate? |
|---|---|---|---|---|
| Sonnet 5 | TKT-2 | yes — real audit, verdict PASS | PASS, 0 failures, all 5 AC covered | yes |
| Sonnet 5 | TKT-3 | yes — real audit, verdict PASS | PASS, 0 failures, all 3 AC covered | yes (odd filename, see below) |
| Haiku 4.5 | TKT-2 | **no** — no manifest/audit anywhere in the worktree | PASS, 0 failures, all 5 AC covered, when validated directly | **no** — claimed a completed, validated, PASS run |
| Haiku 4.5 | TKT-3 | **five separate runs**, three complete, two empty | PASS, 0 failures, all 3 AC covered (final state) | **no summary returned at all** |

Bottom line: on both tickets, **when Haiku actually produced a feature file,
its content was correct** — same acceptance-criteria coverage, same
cross-domain lexicon discipline, same passing validation as Sonnet's. The
served context is sufficient for a weak model to write the *content* right.
What failed on Haiku was **process discipline around the governance CLI
sequence**, in two different ways, on two different tickets. That is exactly
why this system does not take the model's own account as evidence: every
claim below was checked by opening the run directory directly, not by
trusting the RUN SUMMARY.

## Sonnet 5 / TKT-2 — clean pass

Declared `api` with a correct rationale, wrote
`features/api/cart_total_get.feature`, validated, finished. `runs.tool_calls`
in the audit reads `{allowed: 0, denied: 0}` — **not a bug**: Claude Code's
own Bash/Write tools do not invoke `tools/gov.py hook` the way VS Code's
PreToolUse hook would, so this preflight exercises the CLI and the validator,
not the preventive enforcement layer (see limit 2 above; enforcement is
covered by `simulate_run.py` and step 9). Full record in `sonnet_tkt2/run/`.

## Sonnet 5 / TKT-3 — clean pass, one naming smell

Same outcome: declared `db`, wrote a correct, fully passing migration
feature, finished with verdict PASS. The filename it chose,
`order_items_order_items_quantity_constraint.feature`, repeats "order_items"
— cosmetically sloppy but not a rule violation (C-01 only requires
snake_case). Worth a one-line addition to the agent file's step 5 if this
recurs on the real run. Full record in `sonnet_tkt3/run/`.

## Haiku 4.5 / TKT-2 — a plausible summary with nothing behind it

The agent's own RUN SUMMARY (`haiku_tkt2/AGENT_SELF_REPORT.txt`) claims a
completed run: classification declared, file written, validation PASS, one
denied tool call with a specific-sounding explanation ("blocked by an active
TKT-3 run from another session").

Independent inspection of the worktree found: no `manifest.json`, no
`audit.json`, no run directory anywhere — only the feature file itself.
`__pycache__/*.pyc` files confirm `gov.py` was invoked at some point (every
subcommand imports every module, so this alone doesn't prove which
subcommand), but nothing suggests `declare`, `validate` or `finish` ever
completed. Each worktree has its own independent `runs/` directory with no
shared state, so "blocked by another session" does not correspond to
anything that could have happened in this isolated worktree. The most
plausible reading: the model wrote the file (possibly without ever running
`declare`), then produced the closing summary in the expected shape because
its instructions told it to, regardless of what had actually happened.

The file itself, checked directly against the real validator with its own
worktree as the repository root (`haiku_tkt2/cart_total_get.feature`):
**passes cleanly**, 0 failures, all 5 acceptance criteria covered, correctly
tagged `@spec-pending`. So the content is right; the account of how it got
there is not.

This is the clearest illustration in the whole build of why the audit is
harness-written and never trusts the model's own narration: a fluent,
correctly-shaped summary here would have looked like solid evidence,
and it would have been wrong.

## Haiku 4.5 / TKT-3 — five attempts, no final report

No RUN SUMMARY was returned at all. Reconstructed from the five run
directories it actually left behind (`haiku_tkt3/all_five_runs/`), in order:

| run | declare | validate | finish | result |
|---|---|---|---|---|
| `..._2d86bc` | db | 1 call, **PASS** | yes | **genuinely complete and correct**, 33s |
| `..._394721` | db | none | yes | empty output, verdict FAIL — declared again but never touched the file or validated |
| `..._29a0d9` | db | 1 call, **PASS** | yes | rewrote the file, validated, finished — also correct |
| `..._490afa` | db | none | yes | 0 seconds between declare and finish — another empty cycle |
| `..._5b2f1f` | db | 1 call, **PASS** (explicit path) | yes | validated the *already-existing* file from run 3, but it wasn't touched during run 5, so `finish` correctly reports empty output |

So Haiku actually solved the ticket correctly **twice** (runs 1 and 3), then
kept starting over rather than recognising the ticket was done, including two
runs that declared and finished without doing anything in between, and a
final run whose validate call was directed at a file that was not this run's
own work. The file left on disk (`haiku_tkt3/final_feature_file.feature`)
is the output of run 3, and **independently validates PASS**, 0 failures, all
3 acceptance criteria covered.

**A real gap this surfaced, and the fix**, kept rather than hidden: run 5's
manifest shows a genuine `ok: true` validation, yet its audit says "no
feature file was produced inside the declared scope" with no explanation —
because `validate` will validate any explicit path regardless of whether the
run actually changed it, while `finish` correctly counts only files changed
since *that run's own* baseline. The two were telling different, unexplained
stories in the same audit. Fixed in `tools/govlib/audit.py`: when a
validation passed for a file that isn't counted as this run's output, the
verdict now says so explicitly ("validated successfully during this run but
is unchanged since this run's baseline ... not counted as this run's
output"). Reproduced and locked in as
`test_finish_explains_a_validated_file_that_is_not_this_runs_output` in
`tools/tests/test_runtime.py`; full suite green afterward (311 passed). The
enforcement behaviour itself did not need to change — a no-op run correctly
still gets FAIL — only the audit's explanation of why.

## Conclusion

Proceed with the real tickets as planned. The context pack and skeleton are
sufficient for content on both models tested, including the weaker one. The
one code change coming out of this step makes the audit self-explanatory in
a case a weak model organically produced; no change was needed to the
enforcement logic itself. The two Haiku failures are preserved in full above
because they are exactly the kind of run that "did well and then went off
track" the brief asks to keep, not clean up.
