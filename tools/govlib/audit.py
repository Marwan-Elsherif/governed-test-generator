"""The audit record: one JSON document per run, the same shape every
time, written by the harness and never by the model.

Everything in it is derived from things the harness observed: the event
log the hooks wrote, the manifest the CLI wrote, the validator's
findings, and git. The model's own account of what it did appears
nowhere in this file. That is deliberate: an audit that quotes the
agent is an audit of what the agent said, not of what happened.

`schemas/audit.schema.json` fixes the shape; `check_schema` is a small
in-house validator (type, required, properties, items, enum) so that the
governance tool stays dependency-free.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from govlib import conventions as C
from govlib import gitinfo
from govlib import validate as V
from govlib.policy import Policy
from govlib.runstate import Run, list_runs, utcnow
from govlib.tickets import ExpectedDomains, Ticket

SCHEMA_VERSION = "1.0"
AGENT_FILE = ".github/agents/feature-author.agent.md"


# ---------------------------------------------------------------------------
# Minimal schema validation
# ---------------------------------------------------------------------------

_JSON_TYPES = {
    "string": str, "integer": int, "number": (int, float), "boolean": bool,
    "object": dict, "array": list, "null": type(None),
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _JSON_TYPES[expected])


def check_schema(instance: Any, schema: dict, path: str = "$") -> list[str]:
    errors: list[str] = []
    expected = schema.get("type")
    if expected is not None:
        types = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(instance, t) for t in types):
            errors.append(f"{path}: expected {'/'.join(types)}, got {type(instance).__name__}")
            return errors
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in {schema['enum']}")
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                errors.append(f"{path}.{key}: required")
        for key, sub in schema.get("properties", {}).items():
            if key in instance:
                errors.extend(check_schema(instance[key], sub, f"{path}.{key}"))
    if isinstance(instance, list) and "items" in schema:
        for i, item in enumerate(instance):
            errors.extend(check_schema(item, schema["items"], f"{path}[{i}]"))
    return errors


def load_schema(repo_root: Path) -> dict:
    return json.loads((repo_root / "schemas" / "audit.schema.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Building the record
# ---------------------------------------------------------------------------

def classification_match(declared: tuple[str, ...], expected: ExpectedDomains | None) -> str:
    if not declared:
        return "undeclared"
    if expected is None:
        return "unknown"
    d, e = set(declared), set(expected.domains)
    if d == e:
        return "exact"
    if d > e:
        return "superset"
    if d < e:
        return "subset"
    return "mismatch"


def _sha(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _client_info(run: Run) -> dict | None:
    """Producer and versions from the transcript VS Code hands the Stop hook
    (its `session.start` record). The transcript format is documented as
    unstable, so this is best effort and absent when unreadable."""
    for path in run.root.glob("transcript.raw.*"):
        try:
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("type") == "session.start":
                    d = rec.get("data", {})
                    return {
                        "producer": d.get("producer"),
                        "copilot_version": d.get("copilotVersion"),
                        "vscode_version": d.get("vscodeVersion"),
                    }
        except (OSError, ValueError):
            continue
    return None


def _tool_stats(events: list[dict]) -> tuple[dict, list[dict], dict, int, dict]:
    calls = [e for e in events if e.get("event") == "tool_call"]
    allowed = [e for e in calls if e.get("decision") == "allow"]
    denied = [e for e in calls if e.get("decision") == "deny"]
    violations = [
        {"at": e["at"], "tool": e.get("tool"), "category": e.get("category"),
         "paths": e.get("paths", []), "command": e.get("command"), "reason": e.get("reason")}
        for e in denied if e.get("violation")
    ]
    terminal = {
        "allowed": [e.get("command") for e in allowed if e.get("category") == "terminal"],
        "denied": [e.get("command") for e in denied if e.get("category") == "terminal"],
    }
    direct_reads_denied = sum(
        1 for e in denied
        if e.get("category") == "read" and any(p.startswith("conventions/") for p in e.get("paths", []))
    )
    scanned = [e for e in events if e.get("event") == "tool_result"]
    leak = {
        "responses_scanned": len(scanned),
        "hits": [e for e in events if e.get("event") == "leak"],
    }
    return (
        {"total": len(calls), "allowed": len(allowed), "denied": len(denied)},
        violations, terminal, direct_reads_denied, leak,
    )


def build(
    repo_root: Path,
    run: Run,
    policy: Policy,
    shop: C.Shop,
    ticket: Ticket | None,
    expected: ExpectedDomains | None,
    *,
    finalized_by: str,
    integrity: str = "not_configured",
    model: str | None = None,
) -> dict:
    manifest = run.manifest
    events = run.events()
    classification = manifest.get("classification") or {}
    declared = tuple(classification.get("domains", ()))

    # -- git / scope ----------------------------------------------------
    baseline = manifest.get("baseline")
    changes = gitinfo.changes_since(repo_root, baseline)
    changed_files = []
    out_of_scope: list[str] = []
    for ch in changes:
        path = ch["path"]
        if path.startswith("runs/"):
            continue  # the harness's own records
        in_scope = bool(declared) and policy.in_write_scope(path, declared)
        changed_files.append({
            "path": path, "status": ch["status"], "sha256": ch["sha256"],
            "domain": policy.domain_of(path), "in_scope": in_scope,
        })
        if not in_scope:
            out_of_scope.append(path)

    git_dir = run.subdir("git")
    patch = gitinfo.diff_patch(repo_root)
    (git_dir / "diff.patch").write_text(patch, encoding="utf-8")
    (git_dir / "status.txt").write_text(
        "\n".join(f"{c['status']} {c['path']}" for c in changes) + "\n", encoding="utf-8"
    )

    # -- outputs: final validation of every in-scope feature file -------
    outputs = []
    final_files: dict[str, str] = {}
    cross_summary: dict[str, dict[str, int]] = {}
    out_dir = run.subdir("output")
    for cf in changed_files:
        path = cf["path"]
        if not (cf["in_scope"] and path.endswith(".feature")):
            continue
        abs_path = repo_root / path
        if not abs_path.exists():
            continue
        report = V.validate_feature(abs_path, repo_root, ticket=ticket, shop=shop)
        cross = V.cross_check(abs_path, repo_root, ticket=ticket, shop=shop)
        snapshot = out_dir / abs_path.name
        shutil.copyfile(abs_path, snapshot)
        final_files[path] = "PASS" if report.ok else "FAIL"
        cross_summary[path] = {other: len(f) for other, f in cross.items()}
        outputs.append({
            "path": path,
            "domain": report.domain,
            "sha256": _sha(abs_path),
            "scenarios": report.scenario_count,
            "validation": final_files[path],
            "spec_pending": report.spec_pending,
            "adds_to_specification": report.new_objects,
            "ac_coverage": {str(k): v for k, v in report.ac_coverage.items()},
            "uncovered": report.uncovered,
            "failures": [str(f) for f in report.failures],
            "warnings": [str(f) for f in report.warnings],
            "snapshot": f"output/{abs_path.name}",
        })

    tool_calls, violations, terminal, direct_reads_denied, leak = _tool_stats(events)

    # A `validate` call accepts an explicit path and will happily validate a
    # file that was not actually touched during this run (e.g. left over,
    # unchanged, from an earlier run in the same working tree). That call
    # records a genuine `ok: true` in the manifest, but `finish` counts only
    # files changed since *this run's own* baseline as its output, so such a
    # file never appears in `outputs`. Found empirically: a weak-model
    # preflight run re-validated an already-passing file from a prior run,
    # then finished with zero counted output and no explanation for why a
    # file that had just validated clean didn't count. Surfacing it here so
    # the audit explains the apparent contradiction instead of just showing
    # a FAIL verdict next to a passing validation entry.
    validated_but_not_this_runs_output = sorted({
        v["file"] for v in manifest.get("validations", [])
        if v.get("ok") and v.get("file") not in final_files
    })

    # -- verdict ----------------------------------------------------------
    policy_held = not out_of_scope
    all_pass = bool(outputs) and all(o["validation"] == "PASS" for o in outputs)
    match = classification_match(declared, expected)
    reasons: list[str] = []
    if not declared:
        reasons.append("no classification was declared")
    if out_of_scope:
        reasons.append(f"{len(out_of_scope)} file(s) changed outside the declared scope: "
                       + ", ".join(out_of_scope))
    if not outputs:
        reasons.append("no feature file was produced inside the declared scope")
        if validated_but_not_this_runs_output:
            reasons.append(
                "note: " + ", ".join(validated_but_not_this_runs_output)
                + " validated successfully during this run but is unchanged since this "
                "run's baseline (already existed before this run started), so it is not "
                "counted as this run's output; see an earlier run's audit for its record")
    elif not all_pass:
        reasons.append("final validation failed for: "
                       + ", ".join(p for p, s in final_files.items() if s == "FAIL"))
    if integrity == "tampered":
        reasons.append("governance bundle integrity check failed: the conventions or tooling "
                       "on disk are not the ones that were sealed")
    elif integrity == "unsigned":
        reasons.append("governance bundle hashes match but the manifest is unsigned or signed "
                       "by an untrusted key, so it proves consistency, not provenance")
    if match == "unknown":
        reasons.append("no expected classification on file for this ticket; human review")
    elif match not in ("exact", "undeclared"):
        reasons.append(f"classification is a {match} of the expected domains "
                       f"({', '.join(expected.domains) if expected else '?'})")
    warnings = sum(len(o["warnings"]) for o in outputs)
    if warnings:
        reasons.append(f"{warnings} validation warning(s) to review")
    if violations:
        reasons.append(f"{len(violations)} attempted violation(s) were denied; policy held")

    if not policy_held or not all_pass or integrity == "tampered" or not declared:
        status = "FAIL"
    elif match != "exact" or warnings or integrity == "unsigned":
        status = "REVIEW"
    else:
        status = "PASS"
    if status == "PASS" and not reasons:
        reasons.append("policy held, outputs valid, classification matches the expected domains")

    agent_path = repo_root / AGENT_FILE
    transcript = next((p.name for p in run.root.glob("transcript.*")), None)
    client = _client_info(run)

    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.id,
        "ticket": {
            "id": run.ticket_id or (ticket.id if ticket else "unknown"),
            "title": ticket.title if ticket else None,
            "path": ticket.path.relative_to(repo_root).as_posix() if ticket else None,
            "sha256": _sha(ticket.path) if ticket else None,
            "acceptance_criteria_count": ticket.ac_count if ticket else None,
        },
        "session": {
            "session_id": manifest.get("session_id"),
            "started_at": manifest.get("created_at"),
            "finished_at": manifest.get("finished_at") or utcnow(),
            "created_by": manifest.get("created_by", "unknown"),
            "agent": {
                "name": "feature-author" if agent_path.exists() else None,
                "path": AGENT_FILE if agent_path.exists() else None,
                "sha256": _sha(agent_path),
            },
            "model": model,
            "client": client,
        },
        "governance": {
            "integrity": integrity,
            "hooks_active": bool(manifest.get("hooks_active")),
            "policy_sha256": _sha(repo_root / "policy.json") or "",
            "events_recorded": len(events),
            "finalized_by": finalized_by,
        },
        "classification": {
            "declared_domains": list(declared),
            "rationale": classification.get("rationale"),
            "evidence": list(classification.get("evidence", [])),
            "mentioned_not_in_scope": list(classification.get("mentioned_not_in_scope", [])),
            "declared_at": classification.get("declared_at"),
            "amendments": list(classification.get("amendments", [])),
            "expected_domains": list(expected.domains) if expected else None,
            "match": match,
        },
        "conventions": {
            "served": list(manifest.get("conventions_served", [])),
            "common_sha256": _sha(C.common_path(repo_root)),
            "direct_reads_denied": direct_reads_denied,
            "leak_scan": leak,
        },
        "policy": {
            "allowed_write_globs": list(manifest.get("allowed_write_globs", [])),
            "tool_calls": tool_calls,
            "attempted_violations": violations,
            "terminal": terminal,
        },
        "outputs": outputs,
        "git": {
            "head_at_start": (baseline or {}).get("head"),
            "head_at_finish": gitinfo.head(repo_root),
            "changed_files": changed_files,
            "out_of_scope_changes": out_of_scope,
            "patch": "git/diff.patch" if patch else None,
        },
        "validation": {
            "attempts": list(manifest.get("validations", [])),
            "final": {"files": final_files, "all_pass": all_pass},
            "cross_check": cross_summary,
        },
        "verdict": {"status": status, "policy_held": policy_held, "reasons": reasons},
        "artifacts": {"events": "events.jsonl", "served": "served/", "transcript": transcript},
        "notes": list(manifest.get("notes", [])),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _yes(b: bool) -> str:
    return "yes" if b else "no"


def render_markdown(audit: dict) -> str:
    L: list[str] = []
    v = audit["verdict"]
    cl = audit["classification"]
    L.append(f"# Audit — {audit['run_id']}")
    L.append("")
    L.append(f"**Verdict: {v['status']}**  ·  policy held: {_yes(v['policy_held'])}  ·  "
             f"ticket {audit['ticket']['id']}"
             + (f" — {audit['ticket']['title']}" if audit['ticket']['title'] else ""))
    L.append("")
    for r in v["reasons"]:
        L.append(f"- {r}")
    L.append("")

    L.append("## Session")
    L.append("")
    L.append("| field | value |")
    L.append("|---|---|")
    s = audit["session"]
    g = audit["governance"]
    L.append(f"| started | {s['started_at']} |")
    L.append(f"| finished | {s['finished_at']} ({g['finalized_by']}) |")
    L.append(f"| session id | {s['session_id'] or 'n/a'} |")
    L.append(f"| agent | {s['agent']['name'] or 'n/a'} `{(s['agent']['sha256'] or '')[:12]}` |")
    L.append(f"| model | {s['model'] or 'not recorded'} |")
    if s.get("client"):
        c = s["client"]
        L.append(f"| client | {c.get('producer')} {c.get('copilot_version')} on VS Code "
                 f"{c.get('vscode_version')} |")
    L.append(f"| hooks active | {_yes(g['hooks_active'])} |")
    L.append(f"| integrity | {g['integrity']} |")
    L.append(f"| events recorded | {g['events_recorded']} |")
    L.append("")

    L.append("## Classification")
    L.append("")
    L.append(f"- declared: **{', '.join(cl['declared_domains']) or 'none'}**"
             f"  ·  expected: {', '.join(cl['expected_domains']) if cl['expected_domains'] else 'not on file'}"
             f"  ·  match: **{cl['match']}**")
    if cl["rationale"]:
        L.append(f"- rationale: {cl['rationale']}")
    for e in cl["evidence"]:
        L.append(f"- evidence: “{e}”")
    if cl["mentioned_not_in_scope"]:
        L.append(f"- mentioned but out of scope: {', '.join(cl['mentioned_not_in_scope'])}")
    for a in cl["amendments"]:
        L.append(f"- amended at {a.get('at')}: {a.get('previous')} → {a.get('domains')} "
                 f"({a.get('rationale')})")
    L.append("")

    L.append("## Conventions in play")
    L.append("")
    L.append("| domain | file | sha256 | fingerprint | served at |")
    L.append("|---|---|---|---|---|")
    for sv in audit["conventions"]["served"]:
        L.append(f"| {sv['domain']} | {sv['path']} | `{sv['sha256'][:12]}` | "
                 f"`{sv['fingerprint']}` | {sv['served_at']} |")
    c = audit["conventions"]
    L.append("")
    L.append(f"- direct reads of conventions denied: {c['direct_reads_denied']}")
    L.append(f"- leak scan: {c['leak_scan']['responses_scanned']} tool responses scanned, "
             f"{len(c['leak_scan']['hits'])} hit(s)")
    L.append("")

    L.append("## Policy")
    L.append("")
    p = audit["policy"]
    L.append(f"- allowed write paths: {', '.join(p['allowed_write_globs']) or 'none'}")
    L.append(f"- tool calls: {p['tool_calls']['total']} "
             f"({p['tool_calls']['allowed']} allowed, {p['tool_calls']['denied']} denied)")
    L.append(f"- terminal: {len(p['terminal']['allowed'])} allowed, "
             f"{len(p['terminal']['denied'])} denied")
    if p["attempted_violations"]:
        L.append("")
        L.append("Attempted violations (denied before they happened):")
        L.append("")
        L.append("| at | tool | target | reason |")
        L.append("|---|---|---|---|")
        for av in p["attempted_violations"]:
            target = av.get("command") or ", ".join(av.get("paths") or [])
            L.append(f"| {av['at']} | {av['tool']} | `{target}` | {av['reason']} |")
    L.append("")

    L.append("## Outputs")
    L.append("")
    if not audit["outputs"]:
        L.append("_none_")
    for o in audit["outputs"]:
        L.append(f"### `{o['path']}` — {o['validation']}")
        L.append("")
        L.append(f"- domain {o['domain']}, {o['scenarios']} scenario(s), sha256 `{(o['sha256'] or '')[:12]}`, "
                 f"snapshot `{o['snapshot']}`")
        L.append(f"- spec-pending: {_yes(o['spec_pending'])}"
                 + (f"; adds: {', '.join(o['adds_to_specification'])}" if o['adds_to_specification'] else ""))
        if o["ac_coverage"]:
            covered = [f"ac-{k}" for k, v in o["ac_coverage"].items() if v]
            L.append(f"- acceptance criteria covered: {', '.join(covered) or 'none'}"
                     + (f"; **not covered: {', '.join('ac-' + str(n) for n in o['uncovered'])}**"
                        if o["uncovered"] else ""))
        for f in o["failures"]:
            L.append(f"- FAIL {f}")
        for w in o["warnings"]:
            L.append(f"- WARN {w}")
        L.append("")

    L.append("## Git scope check")
    L.append("")
    gi = audit["git"]
    L.append(f"- HEAD at start `{(gi['head_at_start'] or '')[:12]}`, at finish "
             f"`{(gi['head_at_finish'] or '')[:12]}`")
    if gi["changed_files"]:
        L.append("")
        L.append("| path | status | domain | in scope |")
        L.append("|---|---|---|---|")
        for cf in gi["changed_files"]:
            L.append(f"| {cf['path']} | {cf['status']} | {cf['domain'] or '-'} | "
                     f"{'yes' if cf['in_scope'] else '**NO**'} |")
    else:
        L.append("- no files changed")
    L.append("")

    L.append("## Validation history")
    L.append("")
    if not audit["validation"]["attempts"]:
        L.append("_no validate calls during the run_")
    for i, a in enumerate(audit["validation"]["attempts"], start=1):
        L.append(f"{i}. {a['at']} `{a['file']}` → {'PASS' if a['ok'] else 'FAIL'}"
                 + (f" ({len(a['failures'])} failure(s): "
                    + ", ".join(sorted({f.split(' ')[1] for f in a['failures']})) + ")"
                    if a["failures"] else ""))
    cx = audit["validation"]["cross_check"]
    if cx:
        L.append("")
        L.append("Cross-check (each output run against the other domains' rules; must fail):")
        for path, others in cx.items():
            L.append(f"- `{path}`: " + ", ".join(f"{d}: {n} failure(s)" for d, n in others.items()))
    L.append("")

    if audit["notes"]:
        L.append("## Notes")
        L.append("")
        for n in audit["notes"]:
            L.append(f"- {n}")
        L.append("")
    L.append(f"_Raw record: `audit.json`; events: `{audit['artifacts']['events']}`; "
             f"served text: `{audit['artifacts']['served']}`_")
    return "\n".join(L) + "\n"


def write_index(repo_root: Path) -> Path:
    rows = []
    for run in list_runs(repo_root):
        audit_path = run.root / "audit.json"
        if audit_path.exists():
            a = json.loads(audit_path.read_text(encoding="utf-8"))
            rows.append((
                run.id, a["ticket"]["id"], ", ".join(a["classification"]["declared_domains"]),
                a["classification"]["match"], a["verdict"]["status"],
                str(len(a["policy"]["attempted_violations"])),
                ", ".join(o["path"].split("/")[-1] for o in a["outputs"]) or "-",
            ))
        else:
            rows.append((run.id, run.ticket_id or "?", ", ".join(run.domains) or "-",
                         "-", f"({run.status})", "-", "-"))
    lines = ["# Runs", "", "Generated by `python3 tools/gov.py report`. One row per run; "
             "open `runs/<id>/audit.md` for the record.", "",
             "| run | ticket | declared | match | verdict | denied attempts | outputs |",
             "|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append(f"| [{r[0]}]({r[0]}/audit.md) | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} |")
    out = repo_root / "runs" / "INDEX.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
