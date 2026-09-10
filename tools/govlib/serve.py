"""Serving conventions to the agent: the only channel through which a
convention document reaches the model.

`declare` (and `load`) print one block of text: the common rules, the
declared domains' rules with their serve-time fingerprints, each
domain's worked example, a context pack naming the shop documents to
read, the ticket with its acceptance criteria numbered, and a skeleton
of the output file with the header already filled in. One tool result
carries everything the agent needs, which matters on a weak model, and
what was served is snapshotted with its hash so the audit can show the
exact bytes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from govlib import conventions as C
from govlib.runstate import Run, utcnow
from govlib.tickets import Ticket

CONTEXT_PACK = {
    "ui": ["shop/README.md", "shop/ui/pages.md", "shop/ui/journeys.md"],
    "api": ["shop/README.md", "shop/api/openapi.yaml", "shop/api/errors.md"],
    "db": ["shop/README.md", "shop/db/schema.sql", "shop/db/README.md",
           "shop/db/migrations/"],
}
EXEMPLAR = {
    "ui": "features/ui/product_detail_add_to_cart.feature",
    "api": "features/api/products_get.feature",
    "db": "features/db/products_price_check.feature",
}
METHOD_PATH_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/[\w{}/?=&.-]*)")
TABLE_RE = re.compile(r"\b(products|carts|cart_items|orders|order_items)\b")


@dataclass(frozen=True)
class Served:
    domain: str
    path: str
    sha256: str
    fingerprint: str
    served_at: str


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return s or "feature"


def suggested_filename(domain: str, ticket: Ticket) -> str:
    text = f"{ticket.title} {ticket.description}"
    if domain == "api":
        m = METHOD_PATH_RE.search(text)
        if m:
            path = re.sub(r"\{[^}]*\}", "", m.group(2)).strip("/").replace("/", "_")
            return f"{slug(path)}_{m.group(1).lower()}.feature"
    if domain == "db":
        m = TABLE_RE.search(text)
        if m:
            return f"{m.group(1)}_{slug(ticket.title)}.feature"
    return f"{slug(ticket.title)}.feature"


def _ac_block(ticket: Ticket, indent: str = "  # ") -> str:
    return "\n".join(f"{indent}ac-{n}: {text}" for n, text in
                     enumerate(ticket.acceptance_criteria, start=1))


def skeleton(domain: str, ticket: Ticket, fingerprint: str) -> str:
    header = f"# gov: ticket={ticket.id} domain={domain} conventions={domain}@{fingerprint}"
    ac = _ac_block(ticket)
    text = f"{ticket.title} {ticket.description}"
    if domain == "api":
        m = METHOD_PATH_RE.search(text)
        method, path = (m.group(1), m.group(2)) if m else ("<METHOD>", "<path>")
        return f"""{header}
@api @{method.lower()} @{ticket.id}
Feature: API {method} {path}

  Background:
    Given the API is available

  # Add @spec-pending on the feature line above if {method} {path} is not in
  # shop/api/openapi.yaml. One scenario per acceptance criterion, ascending
  # status order, each tagged @status-<code> and @ac-<n>:
{ac}
"""
    if domain == "db":
        m = TABLE_RE.search(text)
        table = m.group(1) if m else "<table>"
        return f"""{header}
@db @table-{table} @{ticket.id}
Feature: DB {table} - <concern>

  Background:
    Given the database schema is at migration "<latest existing migration id>"

  # If this ticket introduces a migration, add @migration-<next number>_<slug>
  # and @spec-pending on the feature line, with @up and @down scenarios.
  # Every scenario that writes rows is @rollback. Acceptance criteria:
{ac}
"""
    return f"""{header}
@ui @{ticket.id}
Feature: UI - <Page> - <capability>
  As a shopper
  I want <goal>
  So that <benefit>

  Background:
    Given I am on the "<Page>" page

  # Scenario names start "Shopper ...". Each scenario is @happy-path or
  # @negative, at least one is @smoke. Add @spec-pending on the feature line
  # if any element you refer to is not in shop/ui/pages.md. Acceptance criteria:
{ac}
"""


def build(repo_root: Path, run: Run, ticket: Ticket, domains: tuple[str, ...]) -> tuple[str, list[Served]]:
    """The served text and the records of what was served."""
    served: list[Served] = []
    snap = run.subdir("served")
    parts: list[str] = []

    parts.append(f"== GOVERNANCE: {ticket.id} declared as [{', '.join(domains)}] ==")
    parts.append(f"Run: runs/{run.id}")
    parts.append("Allowed write paths: " + ", ".join(run.allowed_write_globs))
    parts.append("Everything else is denied and recorded. Reads of conventions/ are denied: "
                 "this output is the only copy you get, and it is logged.")
    parts.append("")

    common = C.common_path(repo_root)
    common_text = common.read_text(encoding="utf-8")
    (snap / "common.md").write_text(common_text, encoding="utf-8")
    parts.append("== CONVENTIONS: common (all domains) ==")
    parts.append(common_text.rstrip())
    parts.append("")

    for domain in domains:
        path = C.conventions_path(repo_root, domain)
        text = path.read_text(encoding="utf-8")
        fp = C.fingerprint(path)
        (snap / f"{domain}.md").write_text(text, encoding="utf-8")
        served.append(Served(domain=domain, path=path.relative_to(repo_root).as_posix(),
                             sha256=C.sha256_of(path), fingerprint=fp, served_at=utcnow()))
        parts.append(f"== CONVENTIONS: {domain}  |  fingerprint: {fp}  (copy this into the "
                     f"file header exactly) ==")
        parts.append(text.rstrip())
        parts.append("")

        exemplar = repo_root / EXEMPLAR[domain]
        if exemplar.exists():
            parts.append(f"== WORKED EXAMPLE: {EXEMPLAR[domain]} ==")
            parts.append(exemplar.read_text(encoding="utf-8").rstrip())
            parts.append("")

        parts.append(f"== CONTEXT PACK: {domain} (read these with the read tool for facts) ==")
        parts.extend(f"- {p}" for p in CONTEXT_PACK[domain])
        parts.append("")

    parts.append(f"== TICKET: {ticket.id} — {ticket.title} ==")
    parts.append(ticket.description)
    parts.append("Acceptance criteria (use these numbers in @ac-<n> tags):")
    parts.append(_ac_block(ticket, indent="  "))
    parts.append("")

    for domain in domains:
        fp = next(s.fingerprint for s in served if s.domain == domain)
        name = suggested_filename(domain, ticket)
        parts.append(f"== SKELETON: features/{domain}/{name} (create this file; keep line 1 "
                     "exactly) ==")
        parts.append(skeleton(domain, ticket, fp).rstrip())
        parts.append("")

    parts.append("== NEXT ==")
    parts.append("1. Read the context pack files you need, then create the feature file(s) at "
                 "the paths above, one per declared domain.")
    parts.append("2. Run: python3 tools/gov.py validate")
    parts.append("3. Fix every FAIL it names (each is a rule id from the conventions above) "
                 "and validate again until every file is PASS.")
    parts.append("4. Run: python3 tools/gov.py finish   (writes the audit record; the run is "
                 "not complete until this succeeds)")
    parts.append("Then reply with the run summary in the format your instructions specify.")

    text = "\n".join(parts) + "\n"
    (snap / "served.txt").write_text(text, encoding="utf-8")
    return text, served
