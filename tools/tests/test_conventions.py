"""Tests for conventions/*.md and the exemplar feature files.

The brief requires the three domain conventions to be "meaningfully
different". These tests make that claim mechanical rather than a matter
of taste: each exemplar must satisfy its own domain's title, background,
naming and lexicon rules, and must *fail* the other two domains' title
patterns while containing words those domains forbid. They also check
that every name an exemplar uses resolves against the shop registries,
so the worked examples the agent is shown are themselves correct.

The full rule engine arrives in step 5; what is pinned here is the
contract between the documents and that engine: rule IDs are contiguous,
unique, and the documents reference exemplars that exist.
"""
import re
from pathlib import Path

import pytest

from govlib import conventions as GC
from govlib import shopspec as S

REPO_ROOT = Path(__file__).resolve().parents[2]
CONV = REPO_ROOT / "conventions"
SHOP = REPO_ROOT / "shop"
DOMAINS = ("ui", "api", "db")

EXEMPLAR = {
    "ui": REPO_ROOT / "features/ui/product_detail_add_to_cart.feature",
    "api": REPO_ROOT / "features/api/products_get.feature",
    "db": REPO_ROOT / "features/db/products_price_check.feature",
}

TITLE_RE = {
    "ui": re.compile(r"^Feature: UI - (.+?) - .+$", re.M),
    "api": re.compile(r"^Feature: API (GET|POST|PUT|PATCH|DELETE) (/\S+)$", re.M),
    "db": re.compile(r"^Feature: DB (\w+) - .+$", re.M),
}
BACKGROUND_FIRST_STEP_RE = {
    "ui": re.compile(r'^\s+Given I am on the "(.+?)" page$', re.M),
    "api": re.compile(r"^\s+Given the API is available$", re.M),
    "db": re.compile(r'^\s+Given the database schema is at migration "(\d{4}_[a-z0-9_]+)"$', re.M),
}
SCENARIO_NAME_RE = {
    "ui": re.compile(r"^\s+Scenario(?: Outline)?: Shopper .+$", re.M),
    "api": re.compile(r"^\s+Scenario(?: Outline)?: returns \d{3} when .+$", re.M),
    "db": re.compile(r"^\s+Scenario(?: Outline)?: \w+: .+$", re.M),
}
RULE_ID_PREFIX = {"common": "C", "ui": "UI", "api": "API", "db": "DB"}


def doc(name: str) -> str:
    return (CONV / f"{name}.md").read_text(encoding="utf-8")


def rule_ids(name: str) -> list[str]:
    prefix = RULE_ID_PREFIX[name]
    return re.findall(rf"^- \*\*({prefix}-\d\d) ", doc(name), re.M)


def forbidden_terms(domain: str) -> list[str]:
    """The backticked items on the domain's 'Forbidden terms' rule line."""
    text = doc(domain)
    m = re.search(r"^- \*\*\w+-\d\d Forbidden terms\.\*\*(.*?)(?=^- \*\*|^## )", text, re.M | re.S)
    assert m, f"{domain}: no 'Forbidden terms' rule found"
    return re.findall(r"`([^`]+)`", m.group(1))


def scannable_lines(feature_text: str) -> str:
    """Feature text with comment lines removed, as C05 specifies."""
    return "\n".join(l for l in feature_text.splitlines() if not l.strip().startswith("#"))


def contains_term(text: str, term: str) -> bool:
    return re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text, re.I) is not None


def scenario_tags(feature_text: str) -> list[tuple[str, str]]:
    """(scenario name, tag line) pairs; the tag line is the non-blank line
    directly above each Scenario line."""
    lines = feature_text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = re.match(r"^\s+Scenario(?: Outline)?: (.+)$", line)
        if m:
            prev = next((l.strip() for l in reversed(lines[:i]) if l.strip()), "")
            out.append((m.group(1), prev if prev.startswith("@") else ""))
    return out


# ---------------------------------------------------------------------------
# Rule IDs: the contract with the validator.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["common", *DOMAINS])
def test_rule_ids_are_contiguous_from_01(name):
    ids = rule_ids(name)
    assert ids, f"{name}: no rule IDs found"
    numbers = [int(i.split("-")[1]) for i in ids]
    assert numbers == list(range(1, len(numbers) + 1)), f"{name}: {ids}"


def test_rule_ids_are_unique_across_all_documents():
    seen: list[str] = []
    for name in ("common", *DOMAINS):
        seen.extend(rule_ids(name))
    assert len(seen) == len(set(seen))


@pytest.mark.parametrize("name", ["common", *DOMAINS])
def test_every_rule_line_has_a_bold_id_and_a_title(name):
    for line in re.findall(r"^- \*\*.*$", doc(name), re.M):
        assert re.match(r"^- \*\*[A-Z]+-\d\d [A-Z][^*]*\.\*\* ", line), line


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_doc_names_an_existing_exemplar(domain):
    m = re.search(r"Worked example: `([^`]+)`", doc(domain))
    assert m, f"{domain}: no worked example reference"
    assert (REPO_ROOT / m.group(1)) == EXEMPLAR[domain]
    assert EXEMPLAR[domain].exists()


@pytest.mark.parametrize("domain", DOMAINS)
def test_domain_doc_defines_target_state_and_forbidden_terms(domain):
    text = doc(domain)
    assert "## Target state (C-07 for" in text
    assert forbidden_terms(domain), f"{domain}: empty forbidden list"


# ---------------------------------------------------------------------------
# Each exemplar satisfies its own domain's shape.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", DOMAINS)
def test_exemplar_matches_own_domain_shape(domain):
    text = EXEMPLAR[domain].read_text(encoding="utf-8")
    first = text.splitlines()[0]
    assert f"@{domain}" in first.split() and "@exemplar" in first.split()
    assert not first.startswith("# gov:"), "exemplars carry no run header"
    assert TITLE_RE[domain].search(text), "title format"
    assert BACKGROUND_FIRST_STEP_RE[domain].search(text), "background first step"
    names = re.findall(r"^\s+Scenario(?: Outline)?: .+$", text, re.M)
    assert names and all(SCENARIO_NAME_RE[domain].match(n) for n in names), names


@pytest.mark.parametrize("domain", DOMAINS)
def test_exemplar_has_no_own_forbidden_terms(domain):
    text = scannable_lines(EXEMPLAR[domain].read_text(encoding="utf-8"))
    hits = [t for t in forbidden_terms(domain) if contains_term(text, t)]
    assert hits == [], f"{domain} exemplar uses its own forbidden terms: {hits}"


@pytest.mark.parametrize("domain", DOMAINS)
def test_every_scenario_in_exemplar_is_traceable(domain):
    text = EXEMPLAR[domain].read_text(encoding="utf-8")
    for name, tags in scenario_tags(text):
        assert re.search(r"@ac-(\d+|extra)\b", tags), f"{name}: {tags}"


# ---------------------------------------------------------------------------
# The domains are meaningfully different: each exemplar fails the other two.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", DOMAINS)
def test_exemplar_fails_the_other_domains_title_and_background(domain):
    text = EXEMPLAR[domain].read_text(encoding="utf-8")
    for other in DOMAINS:
        if other == domain:
            continue
        assert not TITLE_RE[other].search(text), f"{domain} exemplar matches {other} title"
        assert not BACKGROUND_FIRST_STEP_RE[other].search(text), f"{domain} matches {other} background"
        names = re.findall(r"^\s+Scenario(?: Outline)?: .+$", text, re.M)
        assert not any(SCENARIO_NAME_RE[other].match(n) for n in names), f"{domain} names fit {other}"


@pytest.mark.parametrize("domain", DOMAINS)
def test_exemplar_uses_words_the_other_domains_forbid(domain):
    text = scannable_lines(EXEMPLAR[domain].read_text(encoding="utf-8"))
    for other in DOMAINS:
        if other == domain:
            continue
        hits = [t for t in forbidden_terms(other) if contains_term(text, t)]
        assert hits, f"{domain} exemplar contains nothing {other} forbids; lexicons not discriminative"


@pytest.mark.parametrize("domain", DOMAINS)
def test_forbidden_lists_do_not_ban_a_domains_own_required_vocabulary(domain):
    """Derived from the documents rather than a hand-written list.

    An earlier version of this test hardcoded a few words per domain and
    so missed a real contradiction: `select` was both a required UI-06
    interaction verb and a banned UI-09 term, which would have failed
    every ui feature that used it. Two more of the same kind followed.
    This version takes every backticked phrase on a domain's own rule
    lines, which is its required vocabulary, and asserts none of them
    contains a term the same document bans."""
    banned = forbidden_terms(domain)
    for phrase in GC.required_phrases(REPO_ROOT, domain):
        hits = [b for b in banned if contains_term(phrase, b)]
        assert not hits, (
            f"{domain}: its own rules require {phrase!r} but its ban list "
            f"forbids {hits}; a file following the rules would fail C-05"
        )


# ---------------------------------------------------------------------------
# Exemplars resolve against the shop registries.
# ---------------------------------------------------------------------------

def test_ui_exemplar_names_resolve_against_page_registry():
    pages = S.parse_pages(SHOP / "ui/pages.md")
    text = EXEMPLAR["ui"].read_text(encoding="utf-8")
    title_page = TITLE_RE["ui"].search(text).group(1)
    assert title_page in pages
    for page in re.findall(r'the "([^"]+)" page', text):
        assert page in pages, page
    elements = re.findall(r'(?<!the text )the "([^"]+)"(?! page)', text)
    assert elements
    for element in elements:
        assert pages[title_page].has_element(element), element


def test_api_exemplar_resolves_against_spec_and_catalogue():
    spec = S.parse_openapi(SHOP / "api/openapi.yaml")
    text = EXEMPLAR["api"].read_text(encoding="utf-8")
    method, path = TITLE_RE["api"].search(text).groups()
    assert spec.has(method, path)
    assert "@spec-pending" not in text.splitlines()[0]
    template = re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/]+", path) + "$")
    for req_method, req_path in re.findall(r'When I send a (\w+) request to "([^"]+)"', text):
        assert req_method == method and template.match(req_path), req_path
    catalogue = (SHOP / "api/errors.md").read_text(encoding="utf-8")
    for code in re.findall(r'the error code is "([A-Z_]+)"', text):
        assert f"`{code}`" in catalogue, code
    for uuid in re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text):
        assert uuid.startswith("00000000-0000-4000-8000-"), uuid


def test_db_exemplar_resolves_against_schema_and_migrations():
    schema = S.parse_schema(SHOP / "db/schema.sql")
    migrations = {f"{m.number:04d}_{m.name}" for m in S.parse_migrations(SHOP / "db/migrations")}
    text = EXEMPLAR["db"].read_text(encoding="utf-8")
    table = TITLE_RE["db"].search(text).group(1)
    assert table in schema.tables
    assert f"@table-{table}" in text.splitlines()[0]
    for mig in re.findall(r'migration "(\d{4}_[a-z0-9_]+)"', text) + re.findall(r"@migration-(\S+)", text):
        assert mig in migrations, mig
    for name in re.findall(r'constraint "([a-z_]+)"', text):
        assert any(c.name == name for t in schema.tables.values() for c in t.constraints), name
    for header in re.findall(r"^\s+\| (id\s+\|.+)\|\s*$", text, re.M):
        for col in [c.strip() for c in header.strip("|").split("|")]:
            assert schema.tables[table].has_column(col), col
    for uuid in re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text):
        assert uuid.startswith("00000000-0000-4000-8000-"), uuid
    for (name, tags), block in zip(scenario_tags(text), re.split(r"^\s+Scenario:.*$", text, flags=re.M)[1:]):
        writes = re.search(r"(rows exist in|I insert into|I update|I delete from|I apply migration|I roll back migration)", block)
        if writes:
            assert "@rollback" in tags, name
