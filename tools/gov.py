#!/usr/bin/env python3
"""Governance CLI and hook entry point.

    python3 tools/gov.py hook                     (stdin: VS Code hook JSON)
    python3 tools/gov.py declare --ticket TKT-2 --domains api --rationale "..."
    python3 tools/gov.py load
    python3 tools/gov.py validate [paths...]
    python3 tools/gov.py finish [--note "..."]
    python3 tools/gov.py status
    python3 tools/gov.py report
    python3 tools/gov.py new-ticket TKT-7 --title ... --description ... --ac ... [--ac ...]
    python3 tools/gov.py keygen | seal --version 1.0.0 | verify [--strict]
    python3 tools/gov.py bundle --out dist | install --bundle F --target DIR | update

Stdlib only. The repository root is the parent of this file's directory,
so the tool works regardless of the caller's working directory.

The hook entry point never lets an exception escape. VS Code treats a
crashed hook as a non-blocking warning, which would mean "allow"; on an
internal error this file denies anything write-like and records the
error instead.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from govlib import audit as A  # noqa: E402
from govlib import conventions as C  # noqa: E402
from govlib import gitinfo, hookio, integrity, runstate, scope, serve  # noqa: E402
from govlib import validate as V  # noqa: E402
from govlib.policy import load_policy  # noqa: E402
from govlib.tickets import (  # noqa: E402
    TicketParseError, load_expected_domains, parse_all_tickets, parse_ticket,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TICKET_RE = re.compile(r"\bTKT-\d+\b")
HOOK_ERROR_LOG = REPO_ROOT / "runs" / ".hook_errors.log"


def fail(msg: str, code: int = 1) -> int:
    print(f"gov: {msg}", file=sys.stderr)
    return code


def run_view(run: runstate.Run | None) -> scope.RunView:
    if run is None:
        return scope.RunView.none()
    return scope.RunView(active=run.active, declared=run.declared, domains=run.domains,
                         ticket_id=run.ticket_id)


def load_ticket(ticket_id: str):
    return parse_ticket(REPO_ROOT / "tickets" / f"{ticket_id}.md")


def expected_for(ticket_id: str):
    try:
        return load_expected_domains(REPO_ROOT / "eval" / "expected_domains.json").get(ticket_id)
    except (FileNotFoundError, TicketParseError):
        return None


# ---------------------------------------------------------------------------
# hook
# ---------------------------------------------------------------------------

def _banner(run: runstate.Run | None) -> str:
    current = f"active run {run.id} for {run.ticket_id}" if run else "no active run"
    try:
        check = integrity.verify(REPO_ROOT)
        if check.tampered:
            current += (f". WARNING: the governance bundle is {check.state} "
                        f"({check.reasons[0] if check.reasons else 'see gov.py verify'}); "
                        "`declare` will refuse until it is restored or re-sealed")
    except Exception:  # never let the banner break a session
        pass
    return (
        "Governed test generation is active in this repository. To work a ticket, use the "
        "feature-author agent (or /run-ticket TKT-n). During a run: declare the classification "
        "with `python3 tools/gov.py declare` before anything else; only that CLI may run in the "
        "terminal; files may be written only under the declared domains' feature folders; "
        "conventions are served by the CLI and cannot be read directly. "
        f"Status: {current}."
    )


def hook_main() -> int:
    data: dict = {}
    event = "?"
    try:
        data = hookio.read_input()
        event = str(data.get("hook_event_name") or "?")
        cwd = Path(str(data.get("cwd") or REPO_ROOT))
        session_id = data.get("session_id")
        run = runstate.current_run(REPO_ROOT)

        if run is not None and not run.manifest.get("hooks_active"):
            run.manifest["hooks_active"] = True
            run.save()

        if event == "SessionStart":
            if run:
                run.log("session_start", session_id=session_id, source=data.get("source"))
            hookio.emit(hookio.additional_context("SessionStart", _banner(run)))
            return 0

        if event == "UserPromptSubmit":
            prompt = str(data.get("prompt") or "")
            ticket_ids = TICKET_RE.findall(prompt)
            if run is None and ticket_ids:
                run = runstate.new_run(REPO_ROOT, ticket_ids[0], session_id,
                                       created_by="hook:UserPromptSubmit")
                run.manifest["baseline"] = gitinfo.snapshot(REPO_ROOT)
            if run is not None:
                run.manifest.setdefault("prompts", []).append(
                    {"at": runstate.utcnow(), "text": prompt[:2000]})
                run.log("prompt", session_id=session_id, text=prompt[:2000],
                        tickets_mentioned=ticket_ids)
                if ticket_ids and run.ticket_id and ticket_ids[0] != run.ticket_id:
                    run.log("warning", message=f"prompt mentions {ticket_ids[0]} but the active "
                                               f"run is for {run.ticket_id}; not switching")
                run.save()
            return 0

        if event == "PreToolUse":
            tool = str(data.get("tool_name") or "")
            tool_input = data.get("tool_input") or {}
            policy = load_policy(REPO_ROOT)
            decision = scope.decide(tool, tool_input, run_view(run), policy, REPO_ROOT, cwd)
            if run is not None:
                run.log("tool_call", tool=tool, session_id=session_id,
                        tool_use_id=data.get("tool_use_id"), **decision.as_event())
            hookio.emit(hookio.pre_tool_deny(decision.reason) if not decision.allow
                        else hookio.pre_tool_allow())
            return 0

        if event == "PostToolUse":
            if run is None:
                return 0
            tool = str(data.get("tool_name") or "")
            tool_input = data.get("tool_input") or {}
            response = data.get("tool_response")
            text = response if isinstance(response, str) else (
                json.dumps(response)[:200000] if response else "")
            scanned_from = "tool_response" if text else "none"
            # Observed live: VS Code sends an empty tool_response for read_file,
            # and its transcript records only success/failure. A leak scan that
            # trusts tool_response is blind on exactly the calls that matter, so
            # for read-like tools the hook reads the file it named and scans that.
            if not text and scope.classify_tool(tool) == "read":
                text = _read_for_scan(scope.extract_paths(tool, tool_input, cwd, REPO_ROOT))
                scanned_from = "file" if text else "none"
            run.log("tool_result", tool=tool, tool_use_id=data.get("tool_use_id"),
                    response_chars=len(text), scanned_from=scanned_from,
                    preview=text[:200])
            _snapshot_write(run, tool, tool_input)
            _leak_scan(run, tool, text)
            return 0

        if event == "Stop":
            if run is None:
                _attach_transcript(runstate.last_run(REPO_ROOT), data)
                return 0
            already = bool(data.get("stop_hook_active"))
            unfinished = _unfinished_reason(run)
            if unfinished and not already:
                run.log("stop_blocked", reason=unfinished)
                hookio.emit(hookio.stop_block(
                    unfinished + " The run is not complete until `python3 tools/gov.py finish` "
                    "has written the audit record."))
                return 0
            _attach_transcript(run, data)
            if unfinished and already:
                run.log("stop_auto_finalize", reason=unfinished)
                run.manifest.setdefault("notes", []).append(
                    "auto-finalized by the Stop hook after the agent stopped without finishing: "
                    + unfinished)
                run.save()
                finish(run, finalized_by="hook:Stop", quiet=True)
            return 0

        if event in ("SubagentStart", "SubagentStop", "PreCompact"):
            if run:
                run.log(event.lower(), agent_id=data.get("agent_id"),
                        agent_type=data.get("agent_type"), trigger=data.get("trigger"))
            return 0

        if run:
            run.log("unknown_event", name=event)
        return 0

    except Exception as exc:  # fail closed
        HOOK_ERROR_LOG.parent.mkdir(exist_ok=True)
        with HOOK_ERROR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{runstate.utcnow()} {event}: {exc}\n{traceback.format_exc()}\n")
        if event == "PreToolUse":
            tool = str(data.get("tool_name") or "")
            category = scope.classify_tool(tool)
            if category in ("write", "terminal", "search", "subagent", "web", "unknown"):
                hookio.emit(hookio.pre_tool_deny(
                    f"governance hook error ({type(exc).__name__}: {exc}); denied to fail closed"))
            else:
                hookio.emit(hookio.pre_tool_allow())
        return 0


def _snapshot_write(run: runstate.Run, tool: str, tool_input) -> None:
    if scope.classify_tool(tool) != "write" or not isinstance(tool_input, dict):
        return
    content = tool_input.get("content") or tool_input.get("code") or tool_input.get("newString")
    paths = scope.extract_paths(tool, tool_input, REPO_ROOT, REPO_ROOT)
    if not paths:
        return
    attempts = run.subdir("output") / "attempts"
    attempts.mkdir(exist_ok=True)
    n = len(list(attempts.iterdir())) + 1
    target = REPO_ROOT / paths[0]
    body = content if isinstance(content, str) else (
        target.read_text(encoding="utf-8", errors="replace") if target.is_file() else "")
    (attempts / f"{n:03d}_{tool}_{Path(paths[0]).name}").write_text(body, encoding="utf-8")


def _read_for_scan(paths) -> str:
    """Contents of the files a read tool named, for the leak scan. Paths the
    scope module marked '<outside>' are absolute paths beyond the repository
    (VS Code spills long terminal output to its own storage and the model
    reads it back from there); they are scanned too when readable."""
    chunks: list[str] = []
    for rel in paths:
        path = Path(rel[len("<outside>"):]) if rel.startswith("<outside>") else REPO_ROOT / rel
        try:
            if path.is_file() and path.stat().st_size <= 2_000_000:
                chunks.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(chunks)


def _leak_scan(run: runstate.Run, tool: str, text: str) -> None:
    if not text:
        return
    declared = set(run.domains)
    for domain in C.DOMAINS:
        if domain in declared:
            continue
        marker = f"# {domain} conventions"
        fp = C.fingerprint(C.conventions_path(REPO_ROOT, domain))
        for needle in (marker, fp):
            if needle in text:
                run.log("leak", tool=tool, domain=domain, needle=needle)


def _unfinished_reason(run: runstate.Run) -> str | None:
    if not run.declared:
        return "No classification was declared (`python3 tools/gov.py declare ...`)."
    validations = run.manifest.get("validations", [])
    if not validations:
        return "No validation was run (`python3 tools/gov.py validate`)."
    latest: dict[str, bool] = {}
    for v in validations:
        latest[v["file"]] = v["ok"]
    failing = [f for f, ok in latest.items() if not ok]
    if failing:
        return f"The last validation of {', '.join(failing)} failed."
    if run.status != "finished":
        return "`python3 tools/gov.py finish` has not been run."
    return None


def _attach_transcript(run: runstate.Run | None, data: dict) -> None:
    if run is None:
        return
    src = data.get("transcript_path")
    if not src:
        return
    p = Path(str(src))
    if p.is_file():
        try:
            shutil.copyfile(p, run.root / f"transcript.raw{p.suffix or '.txt'}")
            run.log("transcript_attached", source=str(p))
            _backfill_client_info(run)
        except OSError as exc:
            run.log("warning", message=f"could not copy transcript: {exc}")


def _backfill_client_info(run: runstate.Run) -> None:
    """The agent calls `finish` mid-turn, before the chat response ends; the
    Stop hook that attaches the transcript fires only after. So the client
    (Copilot/VS Code version) is never available when finish builds the
    audit -- discovered because TKT-2's audit had it populated only because
    an unrelated `annotate` call happened to run later, and TKT-3's did not,
    since nothing had touched it yet. Patching it in here, automatically,
    the moment the transcript lands, means every run's audit ends up
    complete without anyone having to remember a follow-up command.

    The same ordering left `artifacts.transcript` null in six of the seven
    live audits while `transcript.raw.jsonl` sat next to them (found while
    writing the README, which was about to claim every audit points at its
    transcript). The pointer is patched here for the same reason."""
    audit_path = run.root / "audit.json"
    if not audit_path.exists():
        return
    try:
        record = json.loads(audit_path.read_text(encoding="utf-8"))
        changed = False
        client = A._client_info(run)
        if client and record.get("session", {}).get("client") != client:
            record["session"]["client"] = client
            changed = True
        transcript = A.transcript_name(run)
        if transcript and record.get("artifacts", {}).get("transcript") != transcript:
            record.setdefault("artifacts", {})["transcript"] = transcript
            changed = True
        if changed:
            audit_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                                  encoding="utf-8")
            (run.root / "audit.md").write_text(A.render_markdown(record), encoding="utf-8")
    except (OSError, ValueError, KeyError) as exc:
        run.log("warning", message=f"could not backfill client info: {exc}")


# ---------------------------------------------------------------------------
# declare / load
# ---------------------------------------------------------------------------

def declare(args) -> int:
    policy = load_policy(REPO_ROOT)
    domains = tuple(d.strip() for d in args.domains.split(",") if d.strip())
    bad = [d for d in domains if d not in policy.domains]
    if not domains or bad:
        return fail(f"--domains must be a comma-separated subset of {', '.join(policy.domains)}")
    try:
        ticket = load_ticket(args.ticket)
    except (FileNotFoundError, TicketParseError) as exc:
        return fail(f"cannot read ticket {args.ticket}: {exc}")

    # The bundle is checked before anything is served. A repository whose
    # conventions have been edited since they were sealed is not one whose
    # audit record means anything: the file the agent would be handed is no
    # longer the file that was published, and the fingerprint in the output
    # would attest to the local edit rather than to the governed rules.
    check = integrity.verify(REPO_ROOT)
    if check.tampered:
        run = runstate.current_run(REPO_ROOT)
        if run is not None:
            run.log("integrity_blocked", state=check.state, reasons=list(check.reasons))
            run.save()
        print(f"gov: refusing to serve conventions -- governance bundle is {check.state}",
              file=sys.stderr)
        for reason in check.reasons:
            print(f"  - {reason}", file=sys.stderr)
        print("  Restore the sealed files (git checkout), or re-seal deliberately with "
              "`python3 tools/gov.py seal --version <v>` if the change is intended.",
              file=sys.stderr)
        return 2

    run = runstate.current_run(REPO_ROOT)
    if run is None:
        run = runstate.new_run(REPO_ROOT, ticket.id, None, created_by="cli:declare")
    if run.ticket_id and run.ticket_id != ticket.id:
        run.log("declare_rejected", reason=f"run is for {run.ticket_id}", requested=ticket.id)
        run.save()
        return fail(f"the active run {run.id} is for {run.ticket_id}, not {ticket.id}; "
                    "finish it first")
    if run.declared and not args.amend:
        run.log("declare_rejected", reason="already declared", requested=list(domains))
        return fail(f"classification already declared as [{', '.join(run.domains)}]; "
                    "use --amend (once) with a rationale to change it")
    if args.amend and not run.declared:
        return fail("--amend given but nothing was declared yet")
    if args.amend and len(run.manifest["classification"].get("amendments", [])) >= 1:
        run.log("declare_rejected", reason="amendment limit", requested=list(domains))
        return fail("only one amendment is allowed per run")

    if run.manifest.get("baseline") is None:
        run.manifest["baseline"] = gitinfo.snapshot(REPO_ROOT)

    if args.amend:
        previous = run.manifest["classification"]
        previous.setdefault("amendments", []).append({
            "at": runstate.utcnow(), "previous": list(previous["domains"]),
            "domains": list(domains), "rationale": args.rationale,
        })
        previous["domains"] = list(domains)
        previous["rationale"] = args.rationale
        previous["evidence"] = list(args.evidence or [])
        previous["mentioned_not_in_scope"] = list(args.mentioned or [])
        run.log("declare_amended", domains=list(domains), rationale=args.rationale)
    else:
        run.manifest["classification"] = {
            "domains": list(domains), "rationale": args.rationale,
            "evidence": list(args.evidence or []),
            "mentioned_not_in_scope": list(args.mentioned or []),
            "declared_at": runstate.utcnow(), "amendments": [],
        }
        run.log("declare", domains=list(domains), rationale=args.rationale,
                evidence=list(args.evidence or []), mentioned=list(args.mentioned or []))
    run.manifest["allowed_write_globs"] = list(policy.allowed_write_globs(domains))
    run.manifest["integrity"] = check.as_dict()
    run.manifest["status"] = "declared"
    run.save()

    text, served = serve.build(REPO_ROOT, run, ticket, domains)
    run.manifest["conventions_served"] = [s.__dict__ for s in served]
    run.log("conventions_served", served=[s.__dict__ for s in served])
    run.save()
    print(text)
    return 0


def load(_args) -> int:
    run = runstate.current_run(REPO_ROOT)
    if run is None or not run.declared:
        return fail("no declared run; run `declare` first")
    ticket = load_ticket(run.ticket_id)
    text, served = serve.build(REPO_ROOT, run, ticket, run.domains)
    run.log("conventions_served", served=[s.__dict__ for s in served], reason="load")
    run.save()
    print(text)
    return 0


# ---------------------------------------------------------------------------
# validate / finish
# ---------------------------------------------------------------------------

def _candidate_outputs(run: runstate.Run, policy) -> list[Path]:
    out: list[Path] = []
    for ch in gitinfo.changes_since(REPO_ROOT, run.manifest.get("baseline")):
        p = ch["path"]
        if p.endswith(".feature") and policy.in_write_scope(p, run.domains) and (REPO_ROOT / p).exists():
            out.append(REPO_ROOT / p)
    return out


def validate(args) -> int:
    policy = load_policy(REPO_ROOT)
    run = runstate.current_run(REPO_ROOT)
    ticket = None
    if run is not None and run.ticket_id:
        ticket = load_ticket(run.ticket_id)
    elif args.ticket:
        ticket = load_ticket(args.ticket)

    if args.paths:
        paths = [Path(p) if Path(p).is_absolute() else REPO_ROOT / p for p in args.paths]
    elif run is not None and run.declared:
        paths = _candidate_outputs(run, policy)
        if not paths:
            print("Nothing to validate yet: no .feature file has been created or changed "
                  f"under {', '.join(run.allowed_write_globs)} since the run started.")
            return 1
    else:
        return fail("no active declared run; pass explicit paths")

    shop = C.load_shop(REPO_ROOT)
    all_ok = True
    for path in paths:
        report = V.validate_feature(path, REPO_ROOT, ticket=ticket, shop=shop)
        cross = V.cross_check(path, REPO_ROOT, ticket=ticket, shop=shop)
        print(V.render_report(report, cross))
        print()
        all_ok = all_ok and report.ok
        if run is not None:
            rel = path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
            record = {
                "at": runstate.utcnow(), "file": rel, "domain": report.domain, "ok": report.ok,
                "failures": [str(f) for f in report.failures],
                "warnings": [str(f) for f in report.warnings],
                "new_objects": report.new_objects, "uncovered": report.uncovered,
            }
            run.manifest.setdefault("validations", []).append(record)
            run.log("validate", **record)
            snap = run.subdir("output") / "attempts"
            snap.mkdir(exist_ok=True)
            n = len(list(snap.iterdir())) + 1
            shutil.copyfile(path, snap / f"{n:03d}_validate_{path.name}")
            run.save()
    print("ALL PASS" if all_ok else "NOT PASSING: fix the failures above and validate again")
    return 0 if all_ok else 1


def finish(run: runstate.Run | None = None, *, finalized_by: str = "cli:finish",
           note: str | None = None, quiet: bool = False) -> int:
    run = run or runstate.current_run(REPO_ROOT)
    if run is None:
        return fail("no active run to finish")
    policy = load_policy(REPO_ROOT)
    shop = C.load_shop(REPO_ROOT)
    ticket = load_ticket(run.ticket_id) if run.ticket_id else None
    expected = expected_for(run.ticket_id) if run.ticket_id else None
    if note:
        run.manifest.setdefault("notes", []).append(note)
    run.manifest["finished_at"] = runstate.utcnow()
    run.log("finish", finalized_by=finalized_by)

    recorded = (run.manifest.get("integrity") or {}).get("state")
    record = A.build(REPO_ROOT, run, policy, shop, ticket, expected, finalized_by=finalized_by,
                     model=run.manifest.get("model"),
                     integrity=recorded or integrity.verify(REPO_ROOT).state)
    errors = A.check_schema(record, A.load_schema(REPO_ROOT))
    if errors:
        run.log("audit_schema_errors", errors=errors)
        print("audit record does not match schemas/audit.schema.json:", file=sys.stderr)
        for e in errors:
            print("  " + e, file=sys.stderr)
    (run.root / "audit.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                                         encoding="utf-8")
    (run.root / "audit.md").write_text(A.render_markdown(record), encoding="utf-8")
    run.manifest["status"] = "finished"
    run.save()
    runstate.clear_current(REPO_ROOT)
    A.write_index(REPO_ROOT)

    if not quiet:
        v = record["verdict"]
        print(f"Run {run.id} finished: verdict {v['status']} (policy held: "
              f"{'yes' if v['policy_held'] else 'no'})")
        for r in v["reasons"]:
            print(f"  - {r}")
        print(f"Audit: runs/{run.id}/audit.md")
    return 0 if not errors else 1


def verify_cmd(args) -> int:
    result = integrity.verify(REPO_ROOT, strict=args.strict)
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    else:
        print(result.summary())
        for reason in result.reasons:
            print(f"  - {reason}")
        for label, items in (("modified", result.modified), ("missing", result.missing),
                             ("unexpected", result.extra)):
            for rel in items:
                print(f"  {label}: {rel}")
    return 0 if result.state in (integrity.STATE_OK, integrity.STATE_NOT_CONFIGURED,
                                 integrity.STATE_UNSIGNED) else 1


def seal_cmd(args) -> int:
    key = Path(args.key).expanduser() if args.key else integrity.DEFAULT_KEY_PATH
    use_key = key if (integrity.SIGNING_AVAILABLE and key.exists() and not args.unsigned) else None
    if use_key is None and not args.unsigned:
        print(f"gov: no signing key at {key}; sealing with hashes only. "
              "Run `gov.py keygen` for a signed manifest.", file=sys.stderr)
    try:
        manifest = integrity.seal(REPO_ROOT, args.version, key_path=use_key,
                                  trust_this_key=args.trust_this_key)
    except integrity.IntegrityError as exc:
        return fail(str(exc))
    signed = "signed" if manifest.get("signature") else "unsigned"
    print(f"sealed {len(manifest['files'])} file(s) as {manifest['bundle']} "
          f"{manifest['version']} ({signed}) -> {integrity.MANIFEST_NAME}")
    return 0


def keygen_cmd(args) -> int:
    key = Path(args.key).expanduser() if args.key else integrity.DEFAULT_KEY_PATH
    try:
        public = integrity.generate_key(key)
    except integrity.IntegrityError as exc:
        return fail(str(exc))
    print(f"signing key written to {key} (keep it out of the repository)")
    print(f"public key: {public}")
    print("Add it to policy.json's trusted_public_keys, or re-seal with --trust-this-key.")
    return 0


def bundle_cmd(args) -> int:
    try:
        out = integrity.make_bundle(REPO_ROOT, Path(args.out))
    except integrity.IntegrityError as exc:
        return fail(str(exc))
    print(f"wrote {out} and {Path(args.out) / 'LATEST.json'}")
    return 0


def install_cmd(args) -> int:
    try:
        result = integrity.install(Path(args.bundle), Path(args.target),
                                   trust_key=args.trust_key,
                                   allow_untrusted=args.allow_untrusted)
    except integrity.IntegrityError as exc:
        return fail(str(exc))
    print(f"installed into {args.target}: {result.summary()}")
    return 0 if not result.tampered else 1


def update_cmd(args) -> int:
    try:
        status = integrity.check_update(REPO_ROOT, Path(args.latest))
    except integrity.IntegrityError as exc:
        return fail(str(exc))
    if status["up_to_date"]:
        print(f"up to date: {status['local_version']}")
    else:
        print(f"update available: {status['local_version']} -> {status['published_version']} "
              f"({status['artifact']})")
    return 0


def annotate(args) -> int:
    """Record facts the hooks cannot observe (which model the chat UI showed,
    a reviewer's note) on a finished run.

    This patches the existing audit record; it never rebuilds it. A first
    version rebuilt via A.build(), which recomputes the git scope check
    against the working tree *at annotate time*, so unrelated edits made
    after the run (in that case, this very tooling) were reported as
    out-of-scope changes and flipped a PASS to FAIL. The observed facts of a
    finished run are frozen at finish; annotation may only add to them."""
    run = runstate.load_run(REPO_ROOT, args.run) if args.run else runstate.last_run(REPO_ROOT)
    if run is None:
        return fail("no run to annotate")
    if args.model:
        run.manifest["model"] = args.model
        run.log("annotate", model=args.model)
    for note in args.note or []:
        run.manifest.setdefault("notes", []).append(note)
        run.log("annotate", note=note)
    run.save()
    _backfill_client_info(run)
    audit_path = run.root / "audit.json"
    if audit_path.exists():
        record = json.loads(audit_path.read_text(encoding="utf-8"))
        if args.model:
            record["session"]["model"] = args.model
        record["notes"] = list(run.manifest.get("notes", []))
        audit_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n",
                              encoding="utf-8")
        (run.root / "audit.md").write_text(A.render_markdown(record), encoding="utf-8")
        A.write_index(REPO_ROOT)
    print(f"annotated {run.id}: model={run.manifest.get('model')!r}, "
          f"notes={len(run.manifest.get('notes', []))}")
    return 0


# ---------------------------------------------------------------------------
# status / report / new-ticket
# ---------------------------------------------------------------------------

def status(_args) -> int:
    run = runstate.current_run(REPO_ROOT)
    if run is None:
        print("No active run.")
        last = runstate.last_run(REPO_ROOT)
        if last:
            print(f"Last run: {last.id} ({last.status})")
        return 0
    print(f"Active run: {run.id}")
    print(f"  ticket: {run.ticket_id}   status: {run.status}   hooks active: "
          f"{'yes' if run.manifest.get('hooks_active') else 'no'}")
    print(f"  declared: {', '.join(run.domains) if run.declared else 'not yet'}")
    print(f"  allowed writes: {', '.join(run.allowed_write_globs) or '-'}")
    print(f"  validations: {len(run.manifest.get('validations', []))}   events: {len(run.events())}")
    reason = _unfinished_reason(run)
    print(f"  to finish: {reason or 'ready'}")
    return 0


def report(_args) -> int:
    print(A.write_index(REPO_ROOT))
    return 0


def new_ticket(args) -> int:
    ticket_id = args.id
    if not re.fullmatch(r"TKT-\d+", ticket_id):
        return fail("id must look like TKT-<n>")
    path = REPO_ROOT / "tickets" / f"{ticket_id}.md"
    if path.exists():
        return fail(f"{path} already exists")
    lines = [f"**{ticket_id} — {args.title}**", f"*Description:* {args.description}",
             "*Acceptance criteria:*"] + [f"- {ac}" for ac in args.ac]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    parse_ticket(path)
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    if args.expect:
        eval_path = REPO_ROOT / "eval" / "expected_domains.json"
        data = json.loads(eval_path.read_text(encoding="utf-8"))
        data["tickets"][ticket_id] = {
            "domains": [d.strip() for d in args.expect.split(",")],
            "rationale": args.rationale or "added with new-ticket",
        }
        eval_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"added {ticket_id} to eval/expected_domains.json")
    parse_all_tickets(REPO_ROOT / "tickets")
    return 0


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gov.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("hook")

    p = sub.add_parser("declare")
    p.add_argument("--ticket", required=True)
    p.add_argument("--domains", required=True, help="comma-separated: ui,api,db")
    p.add_argument("--rationale", required=True)
    p.add_argument("--evidence", action="append", help="a quote from the ticket; repeatable")
    p.add_argument("--mentioned", action="append",
                   help="a domain the ticket mentions but does not test; repeatable")
    p.add_argument("--amend", action="store_true")

    sub.add_parser("load")

    p = sub.add_parser("validate")
    p.add_argument("paths", nargs="*")
    p.add_argument("--ticket")

    p = sub.add_parser("finish")
    p.add_argument("--note")

    sub.add_parser("status")
    sub.add_parser("report")

    p = sub.add_parser("verify")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict", action="store_true",
                   help="treat an unsigned or untrusted manifest as tampered (use in CI)")

    p = sub.add_parser("seal")
    p.add_argument("--version", required=True)
    p.add_argument("--key")
    p.add_argument("--unsigned", action="store_true", help="hashes only, no signature")
    p.add_argument("--trust-this-key", action="store_true",
                   help="add the signing key to policy.json's trusted_public_keys")

    p = sub.add_parser("keygen")
    p.add_argument("--key")

    p = sub.add_parser("bundle")
    p.add_argument("--out", default="dist")

    p = sub.add_parser("install")
    p.add_argument("--bundle", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--trust-key", help="public key (hex) the bundle must be signed by")
    p.add_argument("--allow-untrusted", action="store_true")

    p = sub.add_parser("update")
    p.add_argument("--latest", default="dist/LATEST.json")
    p.add_argument("--check", action="store_true", help="accepted for readability; always a check")

    p = sub.add_parser("annotate")
    p.add_argument("--run", help="run id; defaults to the most recent run")
    p.add_argument("--model", help="model as shown in the chat UI (hooks cannot observe it)")
    p.add_argument("--note", action="append")

    p = sub.add_parser("new-ticket")
    p.add_argument("id")
    p.add_argument("--title", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--ac", action="append", required=True)
    p.add_argument("--expect", help="comma-separated expected domains for eval/")
    p.add_argument("--rationale")

    args = parser.parse_args(argv)
    if args.command == "hook":
        return hook_main()
    if args.command == "declare":
        return declare(args)
    if args.command == "load":
        return load(args)
    if args.command == "validate":
        return validate(args)
    if args.command == "finish":
        return finish(note=args.note)
    if args.command == "status":
        return status(args)
    if args.command == "report":
        return report(args)
    if args.command == "annotate":
        return annotate(args)
    if args.command == "verify":
        return verify_cmd(args)
    if args.command == "seal":
        return seal_cmd(args)
    if args.command == "keygen":
        return keygen_cmd(args)
    if args.command == "bundle":
        return bundle_cmd(args)
    if args.command == "install":
        return install_cmd(args)
    if args.command == "update":
        return update_cmd(args)
    if args.command == "new-ticket":
        return new_ticket(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
