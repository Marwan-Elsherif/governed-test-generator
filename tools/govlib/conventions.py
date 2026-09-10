"""Access to the convention documents and the shop specification.

Two things matter here.

First, the fingerprint. It is the first eight hex characters of the
sha256 of the domain's convention document, computed when the document
is *served* to the agent and printed alongside it. It appears in no file
the agent can read, so a feature file whose header carries the right
fingerprint is evidence that the served text was in the model's context,
not merely that a tool ran. Rule C-02 checks it.

Second, the forbidden-term lists are read out of the convention
documents at validation time rather than hardcoded here. The document is
the single source of truth: editing the ban list in
`conventions/ui.md` changes what the validator rejects, with no code
change and no chance of the two drifting apart.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from govlib import shopspec as S

DOMAINS = ("ui", "api", "db")
FINGERPRINT_LENGTH = 8
RESERVED_UUID_PREFIX = "00000000-0000-4000-8000-"
UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")

_FORBIDDEN_RULE_RE = re.compile(
    r"^- \*\*[A-Z]+-\d\d Forbidden terms\.\*\*(.*?)(?=^- \*\*|^## )", re.M | re.S
)
_ERROR_CODE_RE = re.compile(r"^\| `([A-Z_]+)` \| (\d{3}) \|", re.M)


class ConventionsError(ValueError):
    """A convention document is missing or does not have the shape the
    validator relies on."""


def conventions_path(repo_root: Path, domain: str) -> Path:
    if domain not in DOMAINS:
        raise ConventionsError(f"unknown domain {domain!r}")
    return repo_root / "conventions" / f"{domain}.md"


def common_path(repo_root: Path) -> Path:
    return repo_root / "conventions" / "common.md"


def fingerprint_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:FINGERPRINT_LENGTH]


def fingerprint(path: Path) -> str:
    """Serve-time fingerprint of a convention document."""
    return fingerprint_of_bytes(path.read_bytes())


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=None)
def _forbidden_terms_cached(path_str: str, mtime: float) -> tuple[str, ...]:
    text = Path(path_str).read_text(encoding="utf-8")
    m = _FORBIDDEN_RULE_RE.search(text)
    if not m:
        raise ConventionsError(f"{path_str}: no 'Forbidden terms' rule found")
    terms = re.findall(r"`([^`]+)`", m.group(1))
    if not terms:
        raise ConventionsError(f"{path_str}: 'Forbidden terms' rule lists nothing")
    return tuple(terms)


def forbidden_terms(repo_root: Path, domain: str) -> tuple[str, ...]:
    """The banned vocabulary for a domain, read from its document."""
    path = conventions_path(repo_root, domain)
    return _forbidden_terms_cached(str(path), path.stat().st_mtime)


def forbidden_rule_id(repo_root: Path, domain: str) -> str:
    """The rule that owns the ban list, e.g. 'UI-09'. Findings name it
    alongside C-05 so a reviewer can find the list that was applied."""
    text = conventions_path(repo_root, domain).read_text(encoding="utf-8")
    m = re.search(r"^- \*\*([A-Z]+-\d\d) Forbidden terms\.\*\*", text, re.M)
    if not m:
        raise ConventionsError(f"{domain}: no 'Forbidden terms' rule found")
    return m.group(1)


def required_phrases(repo_root: Path, domain: str) -> tuple[str, ...]:
    """Every backticked phrase on the domain's rule lines except the
    forbidden-terms rule. These are vocabulary the domain's own rules
    require, and none of them may appear on its ban list."""
    text = conventions_path(repo_root, domain).read_text(encoding="utf-8")
    out: list[str] = []
    for line_block in re.findall(r"^- \*\*[A-Z]+-\d\d .*?(?=^- \*\*|^## )", text, re.M | re.S):
        if "Forbidden terms" in line_block.splitlines()[0]:
            continue
        out.extend(re.findall(r"`([^`]+)`", line_block))
    return tuple(out)


def term_pattern(term: str) -> re.Pattern[str]:
    """Whole-word, case-insensitive match for a possibly multi-word term."""
    return re.compile(rf"(?<![\w-]){re.escape(term)}(?![\w-])", re.I)


def contains_term(text: str, term: str) -> bool:
    return term_pattern(term).search(text) is not None


@dataclass(frozen=True)
class Shop:
    """Everything the validator cross-references a feature file against."""
    pages: dict[str, S.Page]
    schema: S.Schema
    migrations: tuple[S.Migration, ...]
    api: S.ApiSpec
    error_codes: frozenset[str]

    @property
    def migration_ids(self) -> tuple[str, ...]:
        return tuple(f"{m.number:04d}_{m.name}" for m in self.migrations)

    @property
    def next_migration_id_number(self) -> int:
        return max((m.number for m in self.migrations), default=0) + 1

    def constraint_names(self) -> frozenset[str]:
        return frozenset(
            c.name for t in self.schema.tables.values() for c in t.constraints
        )

    def index_names(self) -> frozenset[str]:
        return frozenset(self.schema.indexes)


def load_shop(repo_root: Path) -> Shop:
    shop = repo_root / "shop"
    errors_text = (shop / "api" / "errors.md").read_text(encoding="utf-8")
    codes = frozenset(code for code, _status in _ERROR_CODE_RE.findall(errors_text))
    if not codes:
        raise ConventionsError(f"{shop / 'api' / 'errors.md'}: no error codes found")
    return Shop(
        pages=S.parse_pages(shop / "ui" / "pages.md"),
        schema=S.parse_schema(shop / "db" / "schema.sql"),
        migrations=S.parse_migrations(shop / "db" / "migrations"),
        api=S.parse_openapi(shop / "api" / "openapi.yaml"),
        error_codes=codes,
    )
