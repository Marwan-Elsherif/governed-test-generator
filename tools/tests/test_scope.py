"""Tests for the scope decision table, path extraction and hook input.

The decision function is pure, so every row of the table in
scope.py's docstring is checked here directly, with no VS Code, no
disk and no run directory. Both field casings VS Code has been seen to
send are exercised through hookio.read_input.
"""
import io
import json
from pathlib import Path

import pytest

from govlib import hookio, scope
from govlib.policy import load_policy

ROOT = Path(__file__).resolve().parents[2]
POLICY = load_policy(ROOT)

NO_RUN = scope.RunView.none()
STARTED = scope.RunView(active=True, declared=False, ticket_id="TKT-2")
API_RUN = scope.RunView(active=True, declared=True, domains=("api",), ticket_id="TKT-2")
UI_API_RUN = scope.RunView(active=True, declared=True, domains=("ui", "api"), ticket_id="TKT-4")


def decide(tool, tool_input, run):
    return scope.decide(tool, tool_input, run, POLICY, ROOT)


# ---------------------------------------------------------------------------
# Tool classification and path extraction
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,category", [
    ("create_file", "write"), ("replace_string_in_file", "write"), ("apply_patch", "write"),
    ("copilot_createFile", "write"), ("editFiles", "write"), ("some_new_rename_tool", "write"),
    ("read_file", "read"), ("list_dir", "read"), ("copilot_readFile", "read"),
    ("run_in_terminal", "terminal"), ("runTerminalCommand", "terminal"),
    ("grep_search", "search"), ("semantic_search", "search"),
    ("runSubagent", "subagent"), ("execution_subagent", "subagent"),
    ("fetch_webpage", "web"), ("manage_todo_list", "read"), ("frobnicate", "unknown"),
    ("tool_search", "meta"),
])
def test_classify_tool(name, category):
    assert scope.classify_tool(name) == category


def test_parse_apply_patch_headers():
    patch = ("*** Begin Patch\n*** Add File: features/api/a.feature\n+x\n"
             "*** Update File: features/db/b.feature\n@@\n-y\n+z\n"
             "*** Delete File: shop/db/schema.sql\n*** Move to: features/ui/c.feature\n*** End Patch")
    assert scope.parse_apply_patch(patch) == [
        "features/api/a.feature", "features/db/b.feature", "shop/db/schema.sql",
        "features/ui/c.feature",
    ]


@pytest.mark.parametrize("tool,tool_input,expected", [
    ("create_file", {"filePath": "features/api/x.feature", "content": "c"}, ("features/api/x.feature",)),
    ("create_file", {"file_path": "features/api/x.feature"}, ("features/api/x.feature",)),
    ("create_file", {"filePath": str(ROOT / "features/api/x.feature")}, ("features/api/x.feature",)),
    ("create_file", {"filePath": "file://" + str(ROOT / "features/api/x.feature")}, ("features/api/x.feature",)),
    ("multi_replace_string_in_file", {"replacements": [
        {"filePath": "features/api/a.feature", "oldString": "1", "newString": "2"},
        {"filePath": "features/db/b.feature", "oldString": "1", "newString": "2"},
    ]}, ("features/api/a.feature", "features/db/b.feature")),
    ("create_file", {"filePath": "/tmp/outside.feature"}, ("<outside>/tmp/outside.feature",)),
    ("list_dir", {"path": "shop"}, ("shop",)),
    ("apply_patch", {"input": "*** Begin Patch\n*** Add File: features/api/p.feature\n+x\n*** End Patch"},
     ("features/api/p.feature",)),
])
def test_extract_paths(tool, tool_input, expected):
    got = scope.extract_paths(tool, tool_input, ROOT, ROOT)
    assert got == expected or (len(got) == 1 and got[0].startswith("<outside>") and expected[0].startswith("<outside>"))


def test_extract_paths_ignores_content_that_merely_contains_slashes():
    paths = scope.extract_paths("create_file", {
        "filePath": "features/api/x.feature",
        "content": 'When I send a GET request to "/cart/{id}/total"\nAnd path /orders',
    }, ROOT, ROOT)
    assert paths == ("features/api/x.feature",)


# ---------------------------------------------------------------------------
# Write decisions
# ---------------------------------------------------------------------------

def test_write_outside_a_run_is_allowed_except_protected_paths():
    assert decide("create_file", {"filePath": "features/api/x.feature", "content": ""}, NO_RUN).allow
    assert decide("create_file", {"filePath": "notes.txt", "content": ""}, NO_RUN).allow
    d = decide("create_file", {"filePath": "conventions/api.md", "content": ""}, NO_RUN)
    assert not d.allow and "protected" in d.reason


def test_write_before_declaring_is_denied():
    d = decide("create_file", {"filePath": "features/api/x.feature", "content": ""}, STARTED)
    assert not d.allow and d.violation and "declare" in d.reason


def test_write_inside_declared_scope_is_allowed():
    d = decide("create_file", {"filePath": "features/api/x.feature", "content": ""}, API_RUN)
    assert d.allow and d.category == "write"


def test_write_to_another_domain_is_a_violation():
    d = decide("create_file", {"filePath": "features/db/x.feature", "content": ""}, API_RUN)
    assert not d.allow and d.violation and "outside the declared scope" in d.reason
    assert "features/api/**" in d.reason


def test_multi_domain_run_allows_both_declared_domains_only():
    assert decide("create_file", {"filePath": "features/ui/a.feature"}, UI_API_RUN).allow
    assert decide("create_file", {"filePath": "features/api/b.feature"}, UI_API_RUN).allow
    assert not decide("create_file", {"filePath": "features/db/c.feature"}, UI_API_RUN).allow


@pytest.mark.parametrize("path", [
    "conventions/api.md", ".github/hooks/governance.json", "tools/gov.py", "policy.json",
    "shop/db/migrations/0004_x.sql", "tickets/TKT-2.md", "eval/expected_domains.json",
    "runs/anything/audit.json", "schemas/audit.schema.json",
])
def test_protected_paths_are_denied_even_in_a_declared_run(path):
    d = decide("create_file", {"filePath": path, "content": ""}, API_RUN)
    assert not d.allow and d.violation


def test_apply_patch_is_denied_if_any_file_is_out_of_scope():
    patch = ("*** Begin Patch\n*** Add File: features/api/a.feature\n+x\n"
             "*** Add File: features/db/b.feature\n+y\n*** End Patch")
    d = decide("apply_patch", {"input": patch}, API_RUN)
    assert not d.allow and "features/db/b.feature" in d.reason


def test_write_with_no_path_fails_closed():
    d = decide("create_file", {"content": "x"}, API_RUN)
    assert not d.allow


def test_write_outside_the_repository_is_denied():
    d = decide("create_file", {"filePath": "/etc/hosts", "content": ""}, API_RUN)
    assert not d.allow and "outside the repository" in d.reason


# ---------------------------------------------------------------------------
# Read decisions
# ---------------------------------------------------------------------------

def test_reads_outside_a_run_are_allowed():
    assert decide("read_file", {"filePath": "conventions/ui.md"}, NO_RUN).allow


def test_conventions_are_never_read_directly_during_a_run():
    for run in (STARTED, API_RUN):
        d = decide("read_file", {"filePath": "conventions/api.md"}, run)
        assert not d.allow and d.violation and "declare" in d.reason


def test_answer_key_and_run_records_are_unreadable_during_a_run():
    assert not decide("read_file", {"filePath": "eval/expected_domains.json"}, API_RUN).allow
    assert not decide("read_file", {"filePath": "runs/x/served/api.md"}, API_RUN).allow


def test_other_domains_exemplars_are_unreadable_but_own_are_fine():
    assert not decide("read_file", {"filePath": "features/db/products_price_check.feature"}, API_RUN).allow
    assert decide("read_file", {"filePath": "features/api/products_get.feature"}, API_RUN).allow


def test_domain_exemplars_are_unreadable_before_declaring():
    assert not decide("read_file", {"filePath": "features/api/products_get.feature"}, STARTED).allow


def test_shop_and_tickets_are_readable_during_a_run():
    assert decide("read_file", {"filePath": "shop/api/openapi.yaml"}, API_RUN).allow
    assert decide("read_file", {"filePath": "tickets/TKT-2.md"}, STARTED).allow
    assert decide("list_dir", {"path": "shop/db/migrations"}, API_RUN).allow


# ---------------------------------------------------------------------------
# Search, subagent, web, unknown
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tool,tool_input", [
    ("grep_search", {"query": "Scenario"}), ("semantic_search", {"query": "cart"}),
    ("runSubagent", {"prompt": "x"}), ("fetch_webpage", {"urls": ["https://x"]}),
])
def test_leak_channels_are_closed_during_a_run(tool, tool_input):
    assert not decide(tool, tool_input, API_RUN).allow
    assert decide(tool, tool_input, NO_RUN).allow


def test_tool_catalogue_lookup_is_allowed_during_a_run():
    """Observed in the first live VS Code run: the model called `tool_search`
    with the query "Run the governed repository CLI command in the terminal
    synchronously" to find the terminal tool. The name-based heuristic
    classified it as a codebase search and denied it. It searches the tool
    catalogue, not the workspace, so it must be allowed."""
    d = decide("tool_search", {"query": "run a command in the terminal"}, API_RUN)
    assert d.allow and d.category == "meta" and not d.violation


def test_unknown_tool_with_paths_fails_closed_during_a_run():
    d = decide("frobnicate", {"targetPath": "features/api/x.feature"}, API_RUN)
    assert not d.allow and "fail closed" in d.reason
    assert decide("frobnicate", {"targetPath": "x"}, NO_RUN).allow


def test_unknown_tool_without_paths_is_allowed():
    assert decide("frobnicate", {"value": 1}, API_RUN).allow


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "python3 tools/gov.py validate",
    "python3 tools/gov.py declare --ticket TKT-2 --domains api --rationale \"x\"",
    "python tools/gov.py finish",
    "cd /Users/x/repo && python3 tools/gov.py status",
    "python3 tools/gov.py validate features/api/x.feature",
])
def test_governance_cli_is_allowed_in_the_terminal(command):
    assert decide("run_in_terminal", {"command": command}, API_RUN).allow


@pytest.mark.parametrize("command", [
    "ls -la", "rm -rf features/db", "cat conventions/ui.md", "git status",
    "python3 tools/gov.py validate; cat conventions/ui.md",
    "python3 tools/gov.py validate && rm x",
    "python3 tools/gov.py validate | tee out.txt",
    "python3 tools/gov.py validate > /tmp/x",
    "python3 tools/gov.py verify",
    "python3 tools/other.py declare",
    "echo python3 tools/gov.py validate",
])
def test_everything_else_is_denied_in_the_terminal(command):
    d = decide("run_in_terminal", {"command": command}, API_RUN)
    assert not d.allow and d.violation


def test_terminal_is_unrestricted_outside_a_run():
    assert decide("run_in_terminal", {"command": "ls"}, NO_RUN).allow


# ---------------------------------------------------------------------------
# Hook input casing
# ---------------------------------------------------------------------------

def test_read_input_normalises_camel_case_top_level_keys():
    raw = json.dumps({"hookEventName": "PreToolUse", "sessionId": "s1", "toolName": "read_file",
                      "toolInput": {"filePath": "x"}, "cwd": "/w"})
    data = hookio.read_input(io.StringIO(raw))
    assert data["hook_event_name"] == "PreToolUse"
    assert data["session_id"] == "s1"
    assert data["tool_name"] == "read_file"
    assert data["tool_input"] == {"filePath": "x"}


def test_read_input_leaves_snake_case_alone_and_survives_empty_stdin():
    data = hookio.read_input(io.StringIO('{"hook_event_name": "Stop", "stop_hook_active": true}'))
    assert data == {"hook_event_name": "Stop", "stop_hook_active": True}
    assert hookio.read_input(io.StringIO("")) == {}


def test_hook_outputs_have_the_documented_shape():
    deny = hookio.pre_tool_deny("no")
    assert deny["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert deny["hookSpecificOutput"]["permissionDecisionReason"] == "no"
    assert hookio.pre_tool_allow()["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert hookio.stop_block("r")["hookSpecificOutput"]["decision"] == "block"
    assert "additionalContext" in hookio.additional_context("SessionStart", "t")["hookSpecificOutput"]
