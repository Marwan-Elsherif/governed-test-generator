"""Parsing for ticket files (tickets/TKT-n.md) and the hidden
expected-domains ground truth (eval/expected_domains.json).

Deliberately stdlib-only, deliberately strict: a malformed ticket should
fail loudly here, at authoring time, rather than silently confuse the
agent or the validator later. A run's evidence is only as trustworthy as
the fixed template it was built on.

Note on eval/expected_domains.json: this file exists for OUR audit
tooling only. The agent must never see it -- the governance hook denies
reads under eval/** during an active run (see docs/PLAN.md SS2.4/SS2.6).
Classification is compared against it only after the agent has already
declared its own answer, never before.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

TICKET_ID_RE = re.compile(r"^TKT-\d+$")
FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
AC_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(\S.*?)\s*$", re.M)

VALID_DOMAINS = ("ui", "api", "db")
EXPECTED_DOMAINS_SCHEMA_VERSION = 1


class TicketParseError(ValueError):
    """A ticket file, or the expected-domains file, does not match the
    fixed template this tool relies on."""


@dataclass(frozen=True)
class Ticket:
    id: str
    title: str
    description: str
    acceptance_criteria: tuple[str, ...]
    path: Path

    @property
    def ac_count(self) -> int:
        return len(self.acceptance_criteria)

    def ac(self, n: int) -> str:
        """1-indexed acceptance criterion text, matching @ac-N tags."""
        return self.acceptance_criteria[n - 1]


@dataclass(frozen=True)
class ExpectedDomains:
    domains: tuple[str, ...]
    rationale: str
    mentioned_not_in_scope: tuple[str, ...] = field(default_factory=tuple)


def _parse_frontmatter(text: str, path: Path) -> tuple[dict[str, str], str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise TicketParseError(f"{path}: missing '---' frontmatter block at top of file")
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise TicketParseError(f"{path}: malformed frontmatter line: {line!r}")
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm, text[m.end():]


def _parse_sections(body: str, path: Path) -> dict[str, str]:
    headers = list(SECTION_RE.finditer(body))
    if not headers:
        raise TicketParseError(f"{path}: no '## ' section headers found")
    sections: dict[str, str] = {}
    for i, h in enumerate(headers):
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        name = h.group(1).strip()
        if name in sections:
            raise TicketParseError(f"{path}: duplicate '## {name}' section")
        sections[name] = body[start:end].strip()
    return sections


def _parse_acceptance_criteria(block: str, path: Path) -> tuple[str, ...]:
    items = AC_ITEM_RE.findall(block)
    if not items:
        raise TicketParseError(
            f"{path}: 'Acceptance Criteria' section has no numbered items "
            "(expected lines like '1. ...')"
        )
    numbers = [int(n) for n, _ in items]
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        raise TicketParseError(
            f"{path}: acceptance criteria must be numbered 1..N with no gaps "
            f"or repeats; found {numbers}, expected {expected}"
        )
    return tuple(text for _, text in items)


def parse_ticket(path: Path) -> Ticket:
    """Parse one tickets/TKT-n.md file. Raises TicketParseError on any
    deviation from the fixed template -- there is no lenient fallback,
    because a silently-misparsed ticket would poison everything built on
    top of it (classification, AC-coverage checks, the audit record)."""
    text = path.read_text(encoding="utf-8")
    fm, body = _parse_frontmatter(text, path)

    for required in ("id", "title"):
        if not fm.get(required):
            raise TicketParseError(f"{path}: frontmatter missing '{required}'")

    if not TICKET_ID_RE.match(fm["id"]):
        raise TicketParseError(f"{path}: id {fm['id']!r} does not match 'TKT-<n>'")

    sections = _parse_sections(body, path)

    description = sections.get("Description", "").strip()
    if not description:
        raise TicketParseError(f"{path}: 'Description' section is missing or empty")

    ac_block = sections.get("Acceptance Criteria", "")
    if not ac_block:
        raise TicketParseError(f"{path}: 'Acceptance Criteria' section is missing or empty")
    acs = _parse_acceptance_criteria(ac_block, path)

    return Ticket(
        id=fm["id"],
        title=fm["title"],
        description=description,
        acceptance_criteria=acs,
        path=path,
    )


def parse_all_tickets(tickets_dir: Path) -> dict[str, Ticket]:
    """Parse every TKT-*.md in a directory. Fails loudly on the first bad
    file, on any id/filename mismatch, or on a duplicate id."""
    result: dict[str, Ticket] = {}
    for p in sorted(tickets_dir.glob("TKT-*.md")):
        t = parse_ticket(p)
        if p.stem != t.id:
            raise TicketParseError(
                f"{p}: filename stem {p.stem!r} does not match frontmatter id {t.id!r}"
            )
        if t.id in result:
            raise TicketParseError(f"{p}: duplicate ticket id {t.id!r}")
        result[t.id] = t
    return result


def load_expected_domains(path: Path) -> dict[str, ExpectedDomains]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != EXPECTED_DOMAINS_SCHEMA_VERSION:
        raise TicketParseError(
            f"{path}: unsupported schema_version {data.get('schema_version')!r}, "
            f"expected {EXPECTED_DOMAINS_SCHEMA_VERSION}"
        )

    tickets = data.get("tickets")
    if not isinstance(tickets, dict) or not tickets:
        raise TicketParseError(f"{path}: missing or empty 'tickets' object")

    result: dict[str, ExpectedDomains] = {}
    for ticket_id, entry in tickets.items():
        if not TICKET_ID_RE.match(ticket_id):
            raise TicketParseError(f"{path}: bad ticket id key {ticket_id!r}")

        domains = tuple(entry.get("domains") or ())
        if not domains:
            raise TicketParseError(f"{path}: {ticket_id} has no domains")
        for d in domains:
            if d not in VALID_DOMAINS:
                raise TicketParseError(f"{path}: {ticket_id} has unknown domain {d!r}")
        if len(set(domains)) != len(domains):
            raise TicketParseError(f"{path}: {ticket_id} lists a domain more than once")

        rationale = (entry.get("rationale") or "").strip()
        if not rationale:
            raise TicketParseError(f"{path}: {ticket_id} has no rationale")

        mentioned = tuple(entry.get("mentioned_not_in_scope") or ())
        for d in mentioned:
            if d not in VALID_DOMAINS:
                raise TicketParseError(
                    f"{path}: {ticket_id} mentioned_not_in_scope has unknown domain {d!r}"
                )

        result[ticket_id] = ExpectedDomains(
            domains=domains, rationale=rationale, mentioned_not_in_scope=mentioned
        )
    return result


def check_ticket_and_eval_consistency(
    tickets: dict[str, Ticket], expected: dict[str, ExpectedDomains]
) -> None:
    """Raise if tickets/ and eval/expected_domains.json have drifted apart.
    Every ticket must have an expected-domains entry and vice versa. This
    is a deliberate forcing function: adding a new ticket (e.g. for a live
    demo) without also recording its expected domain(s) fails immediately
    instead of silently leaving the audit unable to compare against it."""
    missing_eval = sorted(set(tickets) - set(expected))
    orphan_eval = sorted(set(expected) - set(tickets))
    problems = []
    if missing_eval:
        problems.append(f"tickets with no expected_domains entry: {missing_eval}")
    if orphan_eval:
        problems.append(f"expected_domains entries with no matching ticket: {orphan_eval}")
    if problems:
        raise TicketParseError("; ".join(problems))
