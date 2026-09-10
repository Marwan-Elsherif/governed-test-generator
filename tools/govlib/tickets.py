"""Parsing for ticket files (tickets/TKT-n.md) and the hidden
expected-domains ground truth (eval/expected_domains.json).

Deliberately stdlib-only, deliberately strict: a malformed ticket should
fail loudly here, at authoring time, rather than silently confuse the
agent or the validator later. A run's evidence is only as trustworthy as
the fixed template it was built on.

Ticket files are an exact, unannotated copy of each ticket as it appears
in the challenge brief:

    **TKT-n — Title**
    *Description:* ...
    *Acceptance criteria:*
    - ...
    - ...

No frontmatter, no renumbered list, no added commentary. Acceptance
criteria are numbered by their position in the file (the first bullet
after the label is AC1, and so on) rather than by digits typed into the
text, precisely so the file content itself never has to differ from the
source to support `@ac-N` traceability later.

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
TITLE_LINE_RE = re.compile(r"^\*\*(TKT-\d+)\s+—\s+(.+?)\*\*\s*$", re.M)
DESCRIPTION_RE = re.compile(r"^\*Description:\*\s+(.+?)\s*$", re.M)
AC_LABEL_RE = re.compile(r"^\*Acceptance criteria:\*\s*$", re.M)
AC_BULLET_RE = re.compile(r"^-\s+(.+?)\s*$", re.M)

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


def parse_ticket(path: Path) -> Ticket:
    """Parse one tickets/TKT-n.md file in the challenge brief's own
    format (see module docstring). Raises TicketParseError on any
    deviation -- there is no lenient fallback, because a silently
    misparsed ticket would poison everything built on top of it
    (classification, AC-coverage checks, the audit record)."""
    text = path.read_text(encoding="utf-8")

    title_match = TITLE_LINE_RE.search(text)
    if not title_match:
        raise TicketParseError(
            f"{path}: missing title line, expected '**TKT-n — Title**'"
        )
    ticket_id, title = title_match.group(1), title_match.group(2).strip()

    desc_match = DESCRIPTION_RE.search(text)
    if not desc_match:
        raise TicketParseError(f"{path}: missing '*Description:* ...' line")
    description = desc_match.group(1).strip()

    ac_label_match = AC_LABEL_RE.search(text)
    if not ac_label_match:
        raise TicketParseError(
            f"{path}: missing '*Acceptance criteria:*' label line"
        )

    bullets_text = text[ac_label_match.end():]
    acs = tuple(m.group(1).strip() for m in AC_BULLET_RE.finditer(bullets_text))
    if not acs:
        raise TicketParseError(
            f"{path}: no '- ...' bullets found after '*Acceptance criteria:*'"
        )

    return Ticket(
        id=ticket_id,
        title=title,
        description=description,
        acceptance_criteria=acs,
        path=path,
    )


def parse_all_tickets(tickets_dir: Path) -> dict[str, Ticket]:
    """Parse every TKT-*.md in a directory. Fails loudly on the first bad
    file, or on any id/filename mismatch.

    There is deliberately no separate "duplicate id" check: enforcing
    ``path.stem == ticket.id`` per file already makes a cross-file
    duplicate impossible to construct, since glob() cannot return two
    distinct paths with the same stem and suffix in one directory. An
    earlier version of this function carried a dead duplicate-id branch,
    guarded by a test that happened to pass for the wrong reason (the
    word "duplicate" leaked into the error message via pytest's tmp_path
    directory name, which is derived from the test's own function name)
    -- caught only by actually inspecting the raised message, not by the
    green checkmark. Left here as a note because it is exactly the kind
    of mistake this tool exists to make less likely elsewhere.
    """
    result: dict[str, Ticket] = {}
    for p in sorted(tickets_dir.glob("TKT-*.md")):
        t = parse_ticket(p)
        if p.stem != t.id:
            raise TicketParseError(
                f"{p}: filename stem {p.stem!r} does not match title-line id {t.id!r}"
            )
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
