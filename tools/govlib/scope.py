"""The scope decision for one tool call: allow or deny, and why.

This is a pure function of (tool name, tool input, run state, policy).
No disk, no environment, so the whole decision table is unit-testable
without VS Code, and a hook invocation is just: read input, load state,
decide, log, answer.

The table, in words:

  write-like tool   no run       -> deny protected paths, allow the rest
                    run, not yet declared -> deny everything ("declare first")
                    run, declared -> allow only inside the declared domains'
                                     write scope; protected paths always denied
  read-like tool    no run       -> allow
                    run          -> deny conventions/**, runs/**, eval/** and
                                     other domains' feature folders; allow the rest
  search / subagent / web tools  run -> deny (snippet and context leakage channels)
  terminal          no run       -> allow
                    run          -> only the governance CLI, matched by regex
  unknown tool      run, carries path-like arguments -> deny (fail closed)
                    otherwise    -> allow

Paths are extracted defensively: by key name in both casings, from
nested structures, and from apply_patch headers, then resolved against
the hook's cwd and made repository-relative. Anything that resolves
outside the repository is denied for writes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from govlib.policy import Policy

WRITE_TOOLS = frozenset({
    "create_file", "replace_string_in_file", "multi_replace_string_in_file",
    "insert_edit_into_file", "apply_patch", "create_directory", "edit_notebook_file",
    "create_new_jupyter_notebook", "rename_file", "delete_file", "move_file",
    "copilot_createfile", "copilot_replacestring", "copilot_multireplacestring",
    "copilot_insertedit", "copilot_applypatch", "copilot_createdirectory",
    "copilot_editnotebook", "editfiles", "createfile", "createdirectory",
    "editnotebook", "rename", "write", "edit", "multiedit", "notebookedit",
})
READ_TOOLS = frozenset({
    "read_file", "list_dir", "file_search", "get_errors", "problems",
    "get_terminal_output", "terminal_last_command", "terminal_selection",
    "get_changed_files", "changes", "usages", "list_code_usages",
    "get_notebook_summary", "read_notebook_cell_output", "view_image",
    "copilot_readfile", "copilot_listdirectory", "copilot_findfiles",
    "readfile", "listdirectory", "filesearch", "read", "glob", "ls",
    "manage_todo_list", "todos", "memory", "ask_questions", "askquestions",
})
SEARCH_TOOLS = frozenset({
    "grep_search", "semantic_search", "codebase", "textsearch", "text_search",
    "copilot_findtextinfiles", "copilot_searchcodebase", "search_subagent",
    "searchsubagent", "grep", "github_repo", "githubrepo", "github_text_search",
})
SUBAGENT_TOOLS = frozenset({
    "runsubagent", "run_subagent", "execution_subagent", "executionsubagent",
    "agent", "task",
})
WEB_TOOLS = frozenset({"fetch_webpage", "copilot_fetchwebpage", "fetch", "open_simple_browser",
                       "opensimplebrowser", "webfetch", "websearch"})
TERMINAL_TOOLS = frozenset({
    "run_in_terminal", "runinterminal", "runterminalcommand", "run_terminal_command",
    "execute", "bash", "shell", "create_and_run_task", "run_task", "runtask",
    "run_notebook_cell", "runnotebookcell",
})

PATH_KEYS = frozenset({
    "filepath", "file_path", "path", "dirpath", "dir_path", "uri", "file", "files",
    "paths", "oldpath", "old_path", "newpath", "new_path", "source", "destination",
    "target", "notebookpath", "notebook_path",
})
APPLY_PATCH_HEADER_RE = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M
)
PATHLIKE_RE = re.compile(r"^(?:file://)?(?:[A-Za-z]:)?[^\s\"'<>|]*[/\\][^\s\"'<>|]*$")


@dataclass(frozen=True)
class Decision:
    allow: bool
    reason: str
    category: str
    paths: tuple[str, ...] = ()
    command: str | None = None
    violation: bool = False   # a denial the policy considers an attempted breach

    def as_event(self) -> dict[str, Any]:
        return {
            "decision": "allow" if self.allow else "deny",
            "reason": self.reason,
            "category": self.category,
            "paths": list(self.paths),
            "command": self.command,
            "violation": self.violation,
        }


@dataclass(frozen=True)
class RunView:
    """The slice of run state the decision needs. Built from a Run, or
    directly in tests."""
    active: bool
    declared: bool
    domains: tuple[str, ...] = ()
    ticket_id: str | None = None

    @classmethod
    def none(cls) -> "RunView":
        return cls(active=False, declared=False)


def classify_tool(name: str) -> str:
    n = (name or "").strip().lower()
    n_compact = n.replace("-", "_")
    for category, names in (
        ("write", WRITE_TOOLS), ("terminal", TERMINAL_TOOLS), ("search", SEARCH_TOOLS),
        ("subagent", SUBAGENT_TOOLS), ("web", WEB_TOOLS), ("read", READ_TOOLS),
    ):
        if n_compact in names:
            return category
    # Heuristics for names we have not seen, so an unfamiliar spelling of a
    # write tool is still treated as one.
    if any(k in n_compact for k in ("create", "edit", "replace", "insert", "patch",
                                    "write", "rename", "delete", "move", "remove")):
        return "write"
    if any(k in n_compact for k in ("terminal", "command", "exec", "shell")):
        return "terminal"
    if any(k in n_compact for k in ("search", "grep", "codebase")):
        return "search"
    if "subagent" in n_compact or n_compact.endswith("agent"):
        return "subagent"
    if any(k in n_compact for k in ("fetch", "browser", "web", "http")):
        return "web"
    if any(k in n_compact for k in ("read", "list", "get", "view", "find")):
        return "read"
    return "unknown"


def _walk_strings(obj: Any, key: str | None = None) -> Iterable[tuple[str | None, str]]:
    if isinstance(obj, str):
        yield key, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, str(k))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_strings(v, key)


def parse_apply_patch(text: str) -> list[str]:
    out: list[str] = []
    for m in APPLY_PATCH_HEADER_RE.finditer(text or ""):
        out.append(m.group(1) or m.group(2))
    return out


def _normalise(raw: str, cwd: Path, repo_root: Path) -> str:
    p = raw.strip()
    if p.startswith("file://"):
        p = p[len("file://"):]
    path = Path(p)
    if not path.is_absolute():
        path = cwd / path
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    try:
        return resolved.relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return "<outside>" + resolved.as_posix()


def extract_paths(tool_name: str, tool_input: Any, cwd: Path, repo_root: Path) -> tuple[str, ...]:
    """Repository-relative paths the call touches; '<outside>/...' for
    anything not under the repository."""
    found: list[str] = []
    name = (tool_name or "").lower()
    if isinstance(tool_input, dict):
        for key in ("input", "patch"):
            value = tool_input.get(key)
            if isinstance(value, str) and ("apply_patch" in name or "*** Begin Patch" in value):
                found.extend(parse_apply_patch(value))
    for key, value in _walk_strings(tool_input):
        k = (key or "").lower()
        if k in PATH_KEYS or (k.endswith("path") and value):
            found.append(value)
        elif k in ("", "query", "command", "content", "code", "oldstring", "newstring",
                   "old_string", "new_string", "explanation", "input", "patch", "text",
                   "description"):
            continue
        elif PATHLIKE_RE.match(value) and len(value) < 300:
            found.append(value)
    seen: list[str] = []
    for raw in found:
        if not raw or raw in ("/", "."):
            continue
        rel = _normalise(raw, cwd, repo_root)
        if rel not in seen:
            seen.append(rel)
    return tuple(seen)


def has_pathlike_args(tool_input: Any) -> bool:
    for key, value in _walk_strings(tool_input):
        k = (key or "").lower()
        if k in PATH_KEYS or k.endswith("path"):
            return True
    return False


def decide(
    tool_name: str,
    tool_input: Any,
    run: RunView,
    policy: Policy,
    repo_root: Path,
    cwd: Path | None = None,
) -> Decision:
    cwd = cwd or repo_root
    category = classify_tool(tool_name)
    paths = extract_paths(tool_name, tool_input, cwd, repo_root) if category != "terminal" else ()

    if category == "write":
        return _decide_write(paths, run, policy)
    if category == "terminal":
        command = ""
        if isinstance(tool_input, dict):
            command = str(tool_input.get("command") or tool_input.get("cmd") or "")
        return _decide_terminal(command, run, policy)
    if category in ("search", "subagent", "web"):
        if run.active and (category != "search" or True):
            return Decision(False,
                            f"{category} tools are not available during a governed run: they "
                            "pull text from files outside the declared scope into context "
                            "(read the specific files you need with the read tool instead)",
                            category, paths, violation=False)
        return Decision(True, "no governed run active", category, paths)
    if category == "read":
        return _decide_read(paths, run, policy)
    # unknown
    if run.active and has_pathlike_args(tool_input):
        return Decision(False,
                        f"unrecognised tool {tool_name!r} carries file paths; denied during a "
                        "governed run (fail closed)", category, paths, violation=False)
    return Decision(True, f"unrecognised tool {tool_name!r} without file paths", category, paths)


def _decide_write(paths: tuple[str, ...], run: RunView, policy: Policy) -> Decision:
    if not paths:
        return Decision(False, "write tool call names no file path; denied (fail closed)",
                        "write", paths)
    outside = [p for p in paths if p.startswith("<outside>")]
    if outside:
        return Decision(False, f"path resolves outside the repository: {outside[0]}",
                        "write", paths, violation=run.active)
    protected = [p for p in paths if policy.is_protected(p)]
    if protected:
        return Decision(False,
                        f"{protected[0]} is governance-protected and is never written by an "
                        "agent (conventions, tooling, tickets, the shop specification, run "
                        "records)", "write", paths, violation=run.active)
    if not run.active:
        return Decision(True, "no governed run active; ordinary edit", "write", paths)
    if not run.declared:
        return Decision(False,
                        "no classification declared for this run yet. Run "
                        "`python3 tools/gov.py declare --ticket <id> --domains <d,...> "
                        "--rationale \"...\"` before writing any file", "write", paths,
                        violation=True)
    out_of_scope = [p for p in paths if not policy.in_write_scope(p, run.domains)]
    if out_of_scope:
        allowed = ", ".join(policy.allowed_write_globs(run.domains))
        return Decision(False,
                        f"{out_of_scope[0]} is outside the declared scope "
                        f"[{', '.join(run.domains)}] for {run.ticket_id}; allowed: {allowed}. "
                        "If the ticket genuinely requires this domain, re-declare with "
                        "--amend and a rationale; otherwise do not create it",
                        "write", paths, violation=True)
    return Decision(True, f"inside declared scope [{', '.join(run.domains)}]", "write", paths)


def _decide_read(paths: tuple[str, ...], run: RunView, policy: Policy) -> Decision:
    if not run.active:
        return Decision(True, "no governed run active", "read", paths)
    for p in paths:
        if p.startswith("<outside>"):
            continue
        if policy.is_read_denied_during_run(p):
            if p.startswith("conventions/"):
                return Decision(False,
                                f"{p} is not read directly: conventions are served only by "
                                "`python3 tools/gov.py declare` (or `load`) for the declared "
                                "domains, so that what was loaded is recorded", "read", paths,
                                violation=True)
            return Decision(False,
                            f"{p} is not readable during a governed run (run records and "
                            "evaluation data are for the audit, not the agent)", "read", paths,
                            violation=True)
        domain = policy.domain_of(p)
        if (p.startswith("features/") and domain and run.declared
                and domain not in run.domains):
            return Decision(False,
                            f"{p} belongs to the {domain} domain, which is not in this run's "
                            f"scope [{', '.join(run.domains)}]; another domain's examples are "
                            "its conventions by example", "read", paths, violation=True)
        if p.startswith("features/") and domain and not run.declared:
            return Decision(False,
                            f"{p} is a domain example; declare the classification first so "
                            "that only the relevant domain's examples are loaded", "read",
                            paths, violation=True)
    return Decision(True, "read allowed", "read", paths)


def _decide_terminal(command: str, run: RunView, policy: Policy) -> Decision:
    if not run.active:
        return Decision(True, "no governed run active", "terminal", command=command)
    if policy.terminal_allowed(command):
        return Decision(True, "governance CLI", "terminal", command=command)
    return Decision(False,
                    "only the governance CLI may run during a governed run "
                    "(`python3 tools/gov.py declare|load|validate|finish|status`); "
                    f"denied: {command.strip()[:120]!r}", "terminal", command=command,
                    violation=True)
