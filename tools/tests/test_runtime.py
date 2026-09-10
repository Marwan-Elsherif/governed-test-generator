"""Tests for the policy loader, run state, the audit schema checker and
classification matching, plus one end-to-end test that runs the
simulator in a throwaway copy of the repository.

The end-to-end test is the exit check for the governance runtime: the
real hook entry point and the real CLI, driven by synthetic hook
payloads, must produce a schema-valid audit record that contains a
denied write, a failed-then-passed validation, and a PASS verdict.
"""
import json
import tempfile
from pathlib import Path

import pytest

from govlib import audit as A
from govlib import policy as P
from govlib import runstate as R
from govlib.tickets import ExpectedDomains

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Policy and globs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("glob,path,matches", [
    ("features/api/**", "features/api/x.feature", True),
    ("features/api/**", "features/api/steps/x.py", True),
    ("features/api/**", "features/db/x.feature", False),
    ("features/*/x.feature", "features/api/x.feature", True),
    ("features/*/x.feature", "features/api/sub/x.feature", False),
    ("conventions/ui.md", "conventions/ui.md", True),
    ("conventions/ui.md", "conventions/ui.md.bak", False),
    ("**/audit.json", "runs/abc/audit.json", True),
    ("policy.json", "policy.json", True),
])
def test_glob_to_regex(glob, path, matches):
    assert bool(P.glob_to_regex(glob).match(path)) is matches


def test_policy_loads_and_maps_domains():
    pol = P.load_policy(ROOT)
    assert pol.domains == ("ui", "api", "db")
    assert pol.domain_of("features/db/x.feature") == "db"
    assert pol.domain_of("shop/ui/pages.md") == "ui"
    assert pol.domain_of("README.md") is None
    assert pol.allowed_write_globs(("ui", "db")) == ("features/ui/**", "features/db/**")
    assert pol.in_write_scope("features/db/x.feature", ("db",))
    assert not pol.in_write_scope("features/db/x.feature", ("api",))
    assert pol.is_protected("tools/gov.py")
    assert not pol.is_protected("features/api/x.feature")


def test_policy_rejects_missing_or_wrong_version(tmp_path):
    with pytest.raises(P.PolicyError):
        P.load_policy(tmp_path)
    (tmp_path / "policy.json").write_text('{"version": 2}', encoding="utf-8")
    with pytest.raises(P.PolicyError):
        P.load_policy(tmp_path)


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------

def test_run_lifecycle(tmp_path):
    (tmp_path / "runs").mkdir()
    assert R.current_run(tmp_path) is None
    run = R.new_run(tmp_path, "TKT-2", "sess", created_by="hook:UserPromptSubmit")
    assert run.active and not run.declared and run.manifest["hooks_active"]
    assert R.current_run(tmp_path).id == run.id
    run.log("tool_call", tool="read_file", decision="allow")
    run.manifest["classification"] = {"domains": ["api"]}
    run.save()
    again = R.load_run(tmp_path, run.id)
    assert again.declared and again.domains == ("api",)
    assert [e["event"] for e in again.events()] == ["run_created", "tool_call"]
    again.manifest["status"] = "finished"
    again.save()
    assert R.current_run(tmp_path) is None, "a finished run is never current"
    assert R.last_run(tmp_path).id == run.id
    R.clear_current(tmp_path)
    assert not (tmp_path / "runs" / ".current").exists()


def test_cli_created_run_records_that_hooks_were_not_observed(tmp_path):
    (tmp_path / "runs").mkdir()
    run = R.new_run(tmp_path, "TKT-3", None, created_by="cli:declare")
    assert run.manifest["hooks_active"] is False


# ---------------------------------------------------------------------------
# Audit schema checker and classification match
# ---------------------------------------------------------------------------

def test_schema_checker_accepts_valid_and_reports_specific_errors():
    schema = {"type": "object", "required": ["a", "b"],
              "properties": {"a": {"type": "string", "enum": ["x"]},
                             "b": {"type": "array", "items": {"type": "integer"}}}}
    assert A.check_schema({"a": "x", "b": [1, 2]}, schema) == []
    errors = A.check_schema({"a": "y", "b": [1, "two", True]}, schema)
    assert any("$.a" in e and "not in" in e for e in errors)
    assert any("$.b[1]" in e for e in errors)
    assert any("$.b[2]" in e for e in errors), "a bool is not an integer"
    assert any("$.b: required" in e for e in A.check_schema({"a": "x"}, schema))


def test_audit_schema_file_is_itself_well_formed():
    schema = A.load_schema(ROOT)
    assert schema["type"] == "object"
    assert "verdict" in schema["required"]


@pytest.mark.parametrize("declared,expected,match", [
    (("api",), ("api",), "exact"),
    (("api", "db"), ("api",), "superset"),
    (("api",), ("api", "db"), "subset"),
    (("ui",), ("api",), "mismatch"),
    (("api",), None, "unknown"),
    ((), ("api",), "undeclared"),
])
def test_classification_match(declared, expected, match):
    exp = ExpectedDomains(domains=expected, rationale="r") if expected else None
    assert A.classification_match(declared, exp) == match


# ---------------------------------------------------------------------------
# End to end
# ---------------------------------------------------------------------------

def test_simulated_run_produces_a_valid_audit():
    import simulate_run as S

    with tempfile.TemporaryDirectory(prefix="gov-sim-test-") as tmp:
        root = S.make_copy(Path(tmp) / "repo")
        sim = S.Sim(root, verbose=False)
        sim.run()
        assert sim.problems == [], "\n".join(sim.problems)

        run_dir = next(d for d in (root / "runs").iterdir() if d.is_dir())
        audit = json.loads((run_dir / "audit.json").read_text())
        assert audit["verdict"]["status"] == "PASS"
        assert audit["policy"]["tool_calls"]["denied"] >= 10
        assert [v["ok"] for v in audit["validation"]["attempts"]] == [False, True]
        md = (run_dir / "audit.md").read_text()
        assert "Attempted violations" in md
        assert "Cross-check" in md
