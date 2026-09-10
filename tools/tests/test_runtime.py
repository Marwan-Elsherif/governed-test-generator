"""Tests for the policy loader, run state, the audit schema checker and
classification matching, plus one end-to-end test that runs the
simulator in a throwaway copy of the repository.

The end-to-end test is the exit check for the governance runtime: the
real hook entry point and the real CLI, driven by synthetic hook
payloads, must produce a schema-valid audit record that contains a
denied write, a failed-then-passed validation, and a PASS verdict.
"""
import json
import subprocess
import sys
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


def test_finish_explains_a_validated_file_that_is_not_this_runs_output():
    """Found via a weak-model preflight run (see docs/PLAN.md and
    runs/_preflight/): `validate` accepts an explicit path and will
    validate a file left over, unchanged, from an earlier run in the same
    working tree, recording a genuine ok:true. `finish` correctly does not
    count that file as *this* run's output (it counts only files changed
    since this run's own baseline), so the run's audit used to show a bare
    FAIL with no explanation for why a file that had just validated clean
    didn't count. This reproduces the exact sequence against the real CLI
    and asserts the audit now explains it."""
    with tempfile.TemporaryDirectory(prefix="gov-audit-note-test-") as tmp:
        import simulate_run as S

        root = S.make_copy(Path(tmp) / "repo")
        gov = [sys.executable, str(root / "tools" / "gov.py")]

        def cli(*args):
            return subprocess.run(gov + list(args), cwd=root, capture_output=True, text=True)

        # Run 1: a genuine, complete, passing run.
        rel = "features/db/order_items_quantity_constraint.feature"
        (root / rel.rsplit("/", 1)[0]).mkdir(parents=True, exist_ok=True)
        header_proc = cli("declare", "--ticket", "TKT-3", "--domains", "db",
                          "--rationale", "r", "--evidence", "e")
        assert "fingerprint" in header_proc.stdout
        import re
        fp = re.search(r"fingerprint: ([0-9a-f]{8})", header_proc.stdout).group(1)
        (root / rel).write_text(f"""# gov: ticket=TKT-3 domain=db conventions=db@{fp}
@db @table-order_items @TKT-3 @migration-0004_order_items_quantity_constraint @spec-pending
Feature: DB order_items - quantity must be positive

  Background:
    Given the database schema is at migration "0003_products_price_check"

  @up @rollback @ac-2
  Scenario: order_items: the up migration adds the check constraint
    When I apply migration "0004_order_items_quantity_constraint"
    Then the migration succeeds
    And a constraint "chk_order_items_quantity_positive" exists on "order_items"

  @rollback @ac-1
  Scenario: order_items: zero quantity is rejected on insert
    Given migration "0004_order_items_quantity_constraint" is applied
    When I insert into "order_items":
      | id | order_id | product_id | name | quantity | unit_price_cents |
      | 00000000-0000-4000-8000-000000000001 | 00000000-0000-4000-8000-100000000001 | 00000000-0000-4000-8000-200000000001 | x | 0 | 100 |
    Then the statement fails with constraint "chk_order_items_quantity_positive"

  @down @rollback @ac-3
  Scenario: order_items: the down migration removes the constraint
    Given migration "0004_order_items_quantity_constraint" is applied
    When I roll back migration "0004_order_items_quantity_constraint"
    Then the migration succeeds
    And no constraint "chk_order_items_quantity_positive" exists on "order_items"
""", encoding="utf-8")
        assert cli("validate").returncode == 0
        assert cli("finish").returncode == 0

        # Run 2: same ticket, fresh run, the file is NOT touched again --
        # but validate is called with an explicit path naming it anyway.
        cli("declare", "--ticket", "TKT-3", "--domains", "db", "--rationale", "r2", "--evidence", "e2")
        validate2 = cli("validate", rel)
        assert "ALL PASS" in validate2.stdout
        cli("finish")

        run_dirs = sorted(d for d in (root / "runs").iterdir() if d.is_dir())
        assert len(run_dirs) == 2
        second_audit = json.loads((run_dirs[1] / "audit.json").read_text())

        assert second_audit["outputs"] == []
        assert second_audit["verdict"]["status"] == "FAIL"
        note = next((r for r in second_audit["verdict"]["reasons"] if r.startswith("note:")), None)
        assert note is not None, second_audit["verdict"]["reasons"]
        assert rel in note
        assert "not counted as this run's output" in note


def test_annotate_never_recomputes_a_finished_runs_facts():
    """Regression for a bug found on the first live run: `annotate` rebuilt
    the audit, which recomputed the git scope check against the working
    tree at annotate time. Unrelated edits made after the run (the
    governance tooling itself) were then reported as out-of-scope changes
    and the live run's PASS became a FAIL. Annotation must only add the
    model, client and notes to the frozen record."""
    with tempfile.TemporaryDirectory(prefix="gov-annotate-test-") as tmp:
        import re
        import simulate_run as S

        root = S.make_copy(Path(tmp) / "repo")
        gov = [sys.executable, str(root / "tools" / "gov.py")]

        def cli(*args):
            return subprocess.run(gov + list(args), cwd=root, capture_output=True, text=True)

        out = cli("declare", "--ticket", "TKT-2", "--domains", "api", "--rationale", "r",
                  "--evidence", "e").stdout
        fp = re.search(r"fingerprint: ([0-9a-f]{8})", out).group(1)
        rel = "features/api/cart_total_get.feature"
        (root / rel).write_text(S.GOOD_FEATURE.format(
            header=f"# gov: ticket=TKT-2 domain=api conventions=api@{fp}"), encoding="utf-8")
        assert cli("validate").returncode == 0
        assert cli("finish").returncode == 0
        run_dir = next(d for d in (root / "runs").iterdir() if d.is_dir())
        before = json.loads((run_dir / "audit.json").read_text())
        assert before["verdict"]["status"] == "PASS"

        # Unrelated edits after the run, as would happen when tooling is
        # improved between runs.
        (root / "README.md").write_text("changed later\n", encoding="utf-8")
        (root / "tools" / "gov.py").write_text(
            (root / "tools" / "gov.py").read_text() + "\n# touched\n", encoding="utf-8")

        assert cli("annotate", "--run", run_dir.name, "--model", "Auto (GPT-5 mini)",
                   "--note", "reviewed").returncode == 0
        after = json.loads((run_dir / "audit.json").read_text())

        assert after["verdict"] == before["verdict"]
        assert after["git"] == before["git"]
        assert after["outputs"] == before["outputs"]
        assert after["policy"] == before["policy"]
        assert after["governance"]["finalized_by"] == before["governance"]["finalized_by"]
        assert after["session"]["model"] == "Auto (GPT-5 mini)"
        assert after["notes"] == ["reviewed"]
        md = (run_dir / "audit.md").read_text()
        assert "Auto (GPT-5 mini)" in md and "PASS" in md
