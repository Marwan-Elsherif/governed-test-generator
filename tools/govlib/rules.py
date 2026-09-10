"""Rule engine core and the common rules (C-01..C-09).

Every rule here implements one numbered rule in `conventions/common.md`,
and the rule id in a finding is the id in that document. That mapping is
the point: a reviewer reading an audit record can go from a failure
straight to the sentence that was broken, without reading this code.

Rules return findings rather than raising, because a run wants the whole
list of what is wrong, not the first thing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from govlib import conventions as C
from govlib.gherkin import Feature, ParsedFile, Scenario
from govlib.tickets import Ticket

FAIL = "FAIL"
WARN = "WARN"
INFO = "INFO"

HEADER_RE = re.compile(
    r"^# gov: ticket=(TKT-\d+) domain=(ui|api|db) conventions=(ui|api|db)@([0-9a-f]{8})$"
)
FILENAME_RE = re.compile(r"^[a-z0-9_]+$")
AC_TAG_RE = re.compile(r"^@ac-(\d+|extra)$")
TICKET_TAG_RE = re.compile(r"^@(TKT-\d+)$")
MAX_STEPS_PER_SCENARIO = 10
MAX_SCENARIOS_PER_FEATURE = 12


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: str
    message: str
    line: int | None = None

    def __str__(self) -> str:
        where = f":{self.line}" if self.line else ""
        return f"{self.severity} {self.rule}{where} {self.message}"


@dataclass
class Context:
    path: Path
    repo_root: Path
    domain: str
    parsed: ParsedFile
    shop: C.Shop
    ticket: Ticket | None = None
    expected_fingerprint: str | None = None
    _forbidden: tuple[str, ...] | None = field(default=None, repr=False)

    @property
    def feature(self) -> Feature | None:
        return self.parsed.feature

    @property
    def feature_tags(self) -> tuple[str, ...]:
        return self.feature.tags if self.feature else ()

    @property
    def scenarios(self) -> tuple[Scenario, ...]:
        return self.feature.scenarios if self.feature else ()

    @property
    def is_exemplar(self) -> bool:
        return "@exemplar" in self.feature_tags

    @property
    def is_spec_pending(self) -> bool:
        return "@spec-pending" in self.feature_tags

    @property
    def title(self) -> str:
        return self.feature.name if self.feature else ""

    @property
    def folder_domain(self) -> str | None:
        parts = self.path.parts
        return parts[-2] if len(parts) >= 2 and parts[-2] in C.DOMAINS else None

    def forbidden(self) -> tuple[str, ...]:
        if self._forbidden is None:
            self._forbidden = C.forbidden_terms(self.repo_root, self.domain)
        return self._forbidden

    def uuids(self) -> list[str]:
        return C.UUID_RE.findall(self.parsed.scannable_text())


Rule = Callable[[Context], Iterable[Finding]]


class TargetState(Protocol):
    """Each domain module supplies this for rule C-07: whether the thing
    under test is absent from that domain's specification, and what the
    new objects are."""

    def __call__(self, ctx: Context) -> tuple[bool, list[str]]: ...


def run_rules(ctx: Context, rules: Iterable[tuple[str, Rule]]) -> list[Finding]:
    findings: list[Finding] = []
    for rule_id, fn in rules:
        try:
            findings.extend(fn(ctx))
        except Exception as exc:  # a broken rule must not silence the rest
            findings.append(
                Finding(rule_id, FAIL, f"rule raised {type(exc).__name__}: {exc}")
            )
    return findings


# ---------------------------------------------------------------------------
# C-01 .. C-09
# ---------------------------------------------------------------------------

def c01_location(ctx: Context) -> Iterable[Finding]:
    try:
        rel = ctx.path.resolve().relative_to(ctx.repo_root.resolve())
    except ValueError:
        yield Finding("C-01", FAIL, f"{ctx.path} is outside the repository")
        return
    parts = rel.parts
    if len(parts) != 3 or parts[0] != "features":
        yield Finding("C-01", FAIL, f"must live at features/<domain>/<name>.feature, found {rel}")
        return
    if parts[1] != ctx.domain:
        yield Finding("C-01", FAIL, f"folder is {parts[1]!r} but the domain is {ctx.domain!r}")
    if not ctx.path.name.endswith(".feature"):
        yield Finding("C-01", FAIL, f"{ctx.path.name} is not a .feature file")
    stem = ctx.path.name[: -len(".feature")]
    if not FILENAME_RE.match(stem):
        yield Finding("C-01", FAIL, f"{stem!r} is not snake_case (a-z, 0-9, underscore)")


def c02_header(ctx: Context) -> Iterable[Finding]:
    if ctx.is_exemplar:
        return
    header = ctx.parsed.header
    if header is None:
        yield Finding("C-02", FAIL, "missing '# gov:' header on the first line", 1)
        return
    m = HEADER_RE.match(header)
    if not m:
        yield Finding(
            "C-02", FAIL,
            "header must read '# gov: ticket=<TKT-n> domain=<domain> "
            f"conventions=<domain>@<fingerprint>', found {header!r}", 1,
        )
        return
    ticket_id, header_domain, conv_domain, fp = m.groups()
    if header_domain != ctx.domain or conv_domain != ctx.domain:
        yield Finding("C-02", FAIL,
                      f"header names domain {header_domain}/{conv_domain}, expected {ctx.domain}", 1)
    if ctx.ticket and ticket_id != ctx.ticket.id:
        yield Finding("C-02", FAIL,
                      f"header names {ticket_id} but this run is for {ctx.ticket.id}", 1)
    if ctx.expected_fingerprint and fp != ctx.expected_fingerprint:
        yield Finding(
            "C-02", FAIL,
            f"fingerprint {fp} does not match the served conventions "
            f"({ctx.expected_fingerprint}); the served text was not the one used", 1,
        )


def c03_structure(ctx: Context) -> Iterable[Finding]:
    for problem in ctx.parsed.problems:
        yield Finding("C-03", FAIL, problem)
    if ctx.feature is None:
        return
    if ctx.parsed.feature_count != 1:
        yield Finding("C-03", FAIL, f"expected exactly one Feature:, found {ctx.parsed.feature_count}")
    if not ctx.scenarios:
        yield Finding("C-03", FAIL, "no scenarios", ctx.feature.line)
    for sc in ctx.scenarios:
        if not sc.steps_of("When"):
            yield Finding("C-03", FAIL, f"scenario {sc.name!r} has no When step", sc.line)
        if not sc.steps_of("Then"):
            yield Finding("C-03", FAIL, f"scenario {sc.name!r} has no Then step", sc.line)
        seen_action = False
        for step in sc.steps:
            if step.keyword in ("When", "Then"):
                seen_action = True
            elif step.keyword == "Given" and seen_action:
                yield Finding("C-03", FAIL,
                              f"Given after a When or Then: {step.full!r}", step.line)
        if sc.is_outline:
            rows = [len(tbl) for tbl in sc.examples]
            if not rows:
                yield Finding("C-03", FAIL, f"Scenario Outline {sc.name!r} has no Examples:", sc.line)
            elif max(rows) < 2:
                yield Finding("C-03", FAIL,
                              f"Examples: for {sc.name!r} has no data rows", sc.line)


def c04_tags(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    tags = ctx.feature_tags
    line = ctx.feature.line
    if f"@{ctx.domain}" not in tags:
        yield Finding("C-04", FAIL, f"feature is missing the @{ctx.domain} tag", line)
    for other in C.DOMAINS:
        if other != ctx.domain and f"@{other}" in tags:
            yield Finding("C-04", FAIL, f"feature carries another domain's tag @{other}", line)

    ticket_tags = [t for t in tags if TICKET_TAG_RE.match(t)]
    if ctx.is_exemplar:
        if ticket_tags:
            yield Finding("C-04", FAIL,
                          f"an @exemplar feature must not carry a ticket tag ({ticket_tags[0]})", line)
        return
    if len(ticket_tags) != 1:
        yield Finding("C-04", FAIL,
                      f"expected exactly one @TKT-n tag, found {ticket_tags or 'none'}", line)
    elif ctx.ticket and ticket_tags[0] != f"@{ctx.ticket.id}":
        yield Finding("C-04", FAIL,
                      f"feature is tagged {ticket_tags[0]} but this run is for {ctx.ticket.id}", line)


def c05_lexicon(ctx: Context) -> Iterable[Finding]:
    text = ctx.parsed.scannable_text()
    lines = text.splitlines()
    rule_id = C.forbidden_rule_id(ctx.repo_root, ctx.domain)
    for term in ctx.forbidden():
        pattern = C.term_pattern(term)
        for n, line in enumerate(lines, start=1):
            if pattern.search(line):
                yield Finding(
                    "C-05", FAIL,
                    f"{rule_id} forbids {term!r} in {ctx.domain}: {line.strip()!r}", n,
                )
                break


def c06_traceability(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    total = ctx.ticket.ac_count if ctx.ticket else None
    covered: set[int] = set()

    for sc in ctx.scenarios:
        ac_tags = [t for t in sc.tags if AC_TAG_RE.match(t)]
        if not ac_tags:
            yield Finding("C-06", FAIL,
                          f"scenario {sc.name!r} has no @ac-<n> tag", sc.line)
            continue
        for tag in ac_tags:
            value = AC_TAG_RE.match(tag).group(1)
            if value == "extra":
                continue
            n = int(value)
            if total is not None and not (1 <= n <= total):
                yield Finding(
                    "C-06", FAIL,
                    f"{tag} on {sc.name!r}: the ticket has {total} acceptance criteria",
                    sc.line,
                )
            else:
                covered.add(n)

    if total is not None:
        missing = [n for n in range(1, total + 1) if n not in covered]
        if missing:
            yield Finding(
                "C-06", FAIL,
                "no scenario covers acceptance criteri"
                + ("on " if len(missing) == 1 else "a ")
                + ", ".join(str(n) for n in missing),
                ctx.feature.line,
            )


def make_c07(target_state: TargetState) -> Rule:
    """C-07 is one rule with a per-domain notion of 'the specification';
    each domain module supplies that notion."""
    def c07_target_state(ctx: Context) -> Iterable[Finding]:
        if ctx.feature is None:
            return
        expected, new_objects = target_state(ctx)
        declared = ctx.is_spec_pending
        line = ctx.feature.line
        if expected and not declared:
            yield Finding(
                "C-07", FAIL,
                "not in the "
                f"{ctx.domain} specification yet, so the feature must be tagged "
                f"@spec-pending: {', '.join(new_objects)}", line,
            )
        elif declared and not expected:
            yield Finding(
                "C-07", FAIL,
                "@spec-pending, but everything it tests is already specified", line,
            )
        elif expected and declared:
            yield Finding(
                "C-07", INFO,
                "adds to the specification: " + ", ".join(new_objects), line,
            )
    return c07_target_state


def c08_uniqueness(ctx: Context) -> Iterable[Finding]:
    seen: dict[str, int] = {}
    for sc in ctx.scenarios:
        if sc.name in seen:
            yield Finding("C-08", FAIL,
                          f"duplicate scenario name {sc.name!r} (also on line {seen[sc.name]})",
                          sc.line)
        else:
            seen[sc.name] = sc.line
        step_seen: dict[str, int] = {}
        for step in sc.steps:
            key = step.full
            if key in step_seen:
                yield Finding("C-08", FAIL,
                              f"step repeated verbatim in {sc.name!r}: {key!r}", step.line)
            else:
                step_seen[key] = step.line


def c09_size(ctx: Context) -> Iterable[Finding]:
    if len(ctx.scenarios) > MAX_SCENARIOS_PER_FEATURE:
        yield Finding("C-09", WARN,
                      f"{len(ctx.scenarios)} scenarios, more than {MAX_SCENARIOS_PER_FEATURE}")
    for sc in ctx.scenarios:
        if len(sc.steps) > MAX_STEPS_PER_SCENARIO:
            yield Finding("C-09", WARN,
                          f"scenario {sc.name!r} has {len(sc.steps)} steps, "
                          f"more than {MAX_STEPS_PER_SCENARIO}", sc.line)


def common_rules(target_state: TargetState) -> tuple[tuple[str, Rule], ...]:
    return (
        ("C-01", c01_location),
        ("C-02", c02_header),
        ("C-03", c03_structure),
        ("C-04", c04_tags),
        ("C-05", c05_lexicon),
        ("C-06", c06_traceability),
        ("C-07", make_c07(target_state)),
        ("C-08", c08_uniqueness),
        ("C-09", c09_size),
    )
