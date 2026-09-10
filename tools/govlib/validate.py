"""Validation of a feature file against its domain's rules.

Three things come out of a validation, and all three are evidence:

1. Findings, each carrying the rule id from the convention document.
2. The acceptance-criteria coverage matrix: which scenario covers which
   criterion of the ticket.
3. The cross-ruleset result: the same file run against the other two
   domains' rules, which must fail. A file that satisfies more than one
   domain's rules would mean the conventions are not actually
   discriminating between domains, and every claim about "the right
   conventions were loaded" would be weaker for it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from govlib import conventions as C
from govlib import gherkin, rules, rules_api, rules_db, rules_ui
from govlib.rules import FAIL, INFO, WARN, Context, Finding
from govlib.tickets import Ticket

DOMAIN_MODULES = {"ui": rules_ui, "api": rules_api, "db": rules_db}


@dataclass
class Report:
    path: Path
    domain: str
    findings: list[Finding] = field(default_factory=list)
    ac_coverage: dict[int, list[str]] = field(default_factory=dict)
    ac_total: int | None = None
    new_objects: list[str] = field(default_factory=list)
    spec_pending: bool = False
    scenario_count: int = 0

    @property
    def failures(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == FAIL]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == WARN]

    @property
    def notes(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == INFO]

    @property
    def ok(self) -> bool:
        return not self.failures

    @property
    def uncovered(self) -> list[int]:
        if self.ac_total is None:
            return []
        return [n for n in range(1, self.ac_total + 1) if not self.ac_coverage.get(n)]


def domain_of_path(path: Path) -> str | None:
    parts = path.parts
    return parts[-2] if len(parts) >= 2 and parts[-2] in C.DOMAINS else None


def _context(
    path: Path, repo_root: Path, domain: str, ticket: Ticket | None,
    shop: C.Shop, expected_fingerprint: str | None, text: str | None,
) -> Context:
    return Context(
        path=path,
        repo_root=repo_root,
        domain=domain,
        parsed=gherkin.parse(path, text),
        shop=shop,
        ticket=ticket,
        expected_fingerprint=expected_fingerprint,
    )


def validate_feature(
    path: Path,
    repo_root: Path,
    *,
    ticket: Ticket | None = None,
    domain: str | None = None,
    shop: C.Shop | None = None,
    expected_fingerprint: str | None = None,
    check_fingerprint: bool = True,
    text: str | None = None,
) -> Report:
    """Run the common rules and one domain's rules against a file."""
    domain = domain or domain_of_path(path)
    if domain not in DOMAIN_MODULES:
        raise ValueError(f"cannot determine domain for {path}")
    shop = shop or C.load_shop(repo_root)
    if check_fingerprint and expected_fingerprint is None:
        expected_fingerprint = C.fingerprint(C.conventions_path(repo_root, domain))

    module = DOMAIN_MODULES[domain]
    ctx = _context(path, repo_root, domain, ticket, shop, expected_fingerprint, text)

    findings = rules.run_rules(ctx, rules.common_rules(module.target_state))
    findings.extend(rules.run_rules(ctx, module.RULES))

    report = Report(
        path=path,
        domain=domain,
        findings=findings,
        ac_total=ticket.ac_count if ticket else None,
        spec_pending=ctx.is_spec_pending,
        scenario_count=len(ctx.scenarios),
    )
    if ticket:
        coverage: dict[int, list[str]] = {n: [] for n in range(1, ticket.ac_count + 1)}
        for sc in ctx.scenarios:
            for tag in sc.tags:
                m = rules.AC_TAG_RE.match(tag)
                if m and m.group(1) != "extra":
                    coverage.setdefault(int(m.group(1)), []).append(sc.name)
        report.ac_coverage = coverage
    _expected, new_objects = module.target_state(ctx)
    report.new_objects = new_objects
    return report


def cross_check(
    path: Path,
    repo_root: Path,
    *,
    ticket: Ticket | None = None,
    shop: C.Shop | None = None,
    text: str | None = None,
) -> dict[str, list[Finding]]:
    """Run the file against the other two domains' rules.

    Only the domain rules are run, not the common ones: a file in
    features/api/ trivially fails the ui location and header rules, and
    that proves nothing. What is meaningful is that its title, structure,
    vocabulary and assertions do not satisfy another domain.
    """
    own = domain_of_path(path)
    shop = shop or C.load_shop(repo_root)
    out: dict[str, list[Finding]] = {}
    for other, module in DOMAIN_MODULES.items():
        if other == own:
            continue
        ctx = _context(path, repo_root, other, ticket, shop, None, text)
        out[other] = [
            f for f in rules.run_rules(ctx, module.RULES) if f.severity == FAIL
        ]
    return out


def render_report(report: Report, cross: dict[str, list[Finding]] | None = None) -> str:
    """Plain-text validation output, written for the agent to act on and
    for a human to read in the audit record."""
    lines: list[str] = []
    verdict = "PASS" if report.ok else "FAIL"
    lines.append(f"{verdict}  {report.path}  [{report.domain}]")
    lines.append(
        f"  {report.scenario_count} scenario(s), {len(report.failures)} failure(s), "
        f"{len(report.warnings)} warning(s)"
    )

    if report.failures:
        lines.append("")
        lines.append("  Failures (each names the rule it breaks):")
        for f in report.failures:
            where = f" line {f.line}" if f.line else ""
            lines.append(f"    {f.rule}{where}: {f.message}")
    if report.warnings:
        lines.append("")
        lines.append("  Warnings:")
        for f in report.warnings:
            where = f" line {f.line}" if f.line else ""
            lines.append(f"    {f.rule}{where}: {f.message}")
    if report.notes:
        lines.append("")
        for f in report.notes:
            lines.append(f"  Note {f.rule}: {f.message}")

    if report.ac_total:
        lines.append("")
        lines.append("  Acceptance criteria coverage:")
        for n in range(1, report.ac_total + 1):
            names = report.ac_coverage.get(n) or []
            mark = "covered" if names else "NOT COVERED"
            detail = "; ".join(names) if names else ""
            lines.append(f"    ac-{n}: {mark}{': ' + detail if detail else ''}")

    if report.new_objects:
        lines.append("")
        lines.append("  Adds to the specification:")
        for obj in report.new_objects:
            lines.append(f"    {obj}")

    if cross is not None:
        lines.append("")
        lines.append("  Cross-check against the other domains' rules:")
        for other, findings in sorted(cross.items()):
            if findings:
                lines.append(
                    f"    {other}: fails {len(findings)} rule(s), as it should "
                    f"({', '.join(sorted({f.rule for f in findings}))})"
                )
            else:
                lines.append(
                    f"    {other}: PASSES the {other} rules, which means the two rule "
                    "sets do not distinguish these domains"
                )
    return "\n".join(lines)
