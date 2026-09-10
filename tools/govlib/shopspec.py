"""Parsers for the system-under-test specification in shop/.

The shop documents are not decoration: the validator cross-references
generated feature files against them (does this page exist, is this
element named in the registry, is this a real table and column, is this
endpoint in the spec). That only works if the documents are machine
readable, so each has a fixed shape and a parser here.

Stdlib only, and deliberately shallow. In particular openapi.yaml is
scanned for path templates and methods with a small line scanner rather
than parsed as YAML: that is all the validator needs, and it keeps
tools/gov.py free of any dependency that a consuming repo would have to
install before the governance hook could run.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# --- shop/ui/pages.md ------------------------------------------------------

PAGE_HEADING_RE = re.compile(r"^## +(.+?) *$", re.M)
ROUTE_RE = re.compile(r"^- \*\*Route:\*\* +`(.+?)` *$", re.M)
TABLE_ROW_RE = re.compile(r"^\| *(.+?) *\| *(.+?) *\| *(.+?) *\| *$", re.M)

# --- shop/db/schema.sql ----------------------------------------------------

CREATE_TABLE_RE = re.compile(r"^CREATE TABLE +(\w+) *\((.*?)^\);", re.M | re.S)
CREATE_INDEX_RE = re.compile(
    r"^CREATE (?:UNIQUE +)?INDEX +(\w+) +ON +(\w+) *\(([^)]*)\)", re.M
)
CONSTRAINT_RE = re.compile(
    r"^CONSTRAINT +(\w+) +(PRIMARY KEY|FOREIGN KEY|UNIQUE|CHECK)\b *(.*)$",
    re.I | re.S,
)

CONSTRAINT_PREFIXES = {
    "PRIMARY KEY": "pk_",
    "FOREIGN KEY": "fk_",
    "UNIQUE": "uq_",
    "CHECK": "chk_",
}
INDEX_PREFIX = "idx_"

# --- shop/db/migrations/ ---------------------------------------------------

MIGRATION_FILENAME_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")
MIGRATE_UP_MARKER = "-- migrate:up"
MIGRATE_DOWN_MARKER = "-- migrate:down"

# --- shop/api/openapi.yaml -------------------------------------------------

OPENAPI_PATH_RE = re.compile(r"^  (/\S*):\s*$")
OPENAPI_METHOD_RE = re.compile(
    r"^    (get|post|put|patch|delete|head|options|trace):\s*$"
)
OPENAPI_TOP_LEVEL_RE = re.compile(r"^(\w[\w-]*):")
OPENAPI_PARAM_NAME_RE = re.compile(r"^\s*- name: +(\S+) *$", re.M)


class ShopSpecError(ValueError):
    """A shop specification document does not match its fixed shape."""


@dataclass(frozen=True)
class Page:
    name: str
    route: str
    elements: tuple[str, ...]

    def has_element(self, name: str) -> bool:
        return name in self.elements


@dataclass(frozen=True)
class Constraint:
    name: str
    kind: str
    body: str


@dataclass(frozen=True)
class Column:
    name: str
    sql_type: str


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    constraints: tuple[Constraint, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def has_column(self, name: str) -> bool:
        return name in self.column_names

    def checks_on(self, column: str) -> tuple[Constraint, ...]:
        """CHECK constraints whose body mentions the given column."""
        return tuple(
            c for c in self.constraints
            if c.kind == "CHECK" and re.search(rf"\b{re.escape(column)}\b", c.body)
        )


@dataclass(frozen=True)
class Index:
    name: str
    table: str
    columns: tuple[str, ...]


@dataclass(frozen=True)
class Schema:
    tables: dict[str, Table]
    indexes: dict[str, Index]

    def indexes_on(self, table: str, column: str) -> tuple[Index, ...]:
        return tuple(
            i for i in self.indexes.values()
            if i.table == table and column in i.columns
        )


@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    path: Path
    up: str
    down: str


@dataclass(frozen=True)
class Operation:
    path: str
    method: str
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class ApiSpec:
    operations: dict[tuple[str, str], Operation]

    @property
    def paths(self) -> tuple[str, ...]:
        seen: list[str] = []
        for path, _ in self.operations:
            if path not in seen:
                seen.append(path)
        return tuple(seen)

    def has(self, method: str, path: str) -> bool:
        return (path, method.lower()) in self.operations

    def methods_for(self, path: str) -> tuple[str, ...]:
        return tuple(
            sorted(m for (p, m) in self.operations if p == path)
        )


def parse_pages(path: Path) -> dict[str, Page]:
    """Parse shop/ui/pages.md into the page and element registry."""
    text = path.read_text(encoding="utf-8")
    headings = list(PAGE_HEADING_RE.finditer(text))
    if not headings:
        raise ShopSpecError(f"{path}: no '## <page name>' headings found")

    pages: dict[str, Page] = {}
    for i, h in enumerate(headings):
        start = h.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        block = text[start:end]
        name = h.group(1).strip()

        route_match = ROUTE_RE.search(block)
        if not route_match:
            raise ShopSpecError(f"{path}: page '{name}' has no '- **Route:** `...`' line")

        elements: list[str] = []
        for row in TABLE_ROW_RE.finditer(block):
            first = row.group(1).strip()
            # Skip the header row and the |---|---|---| separator.
            if first in ("Element", "") or set(first) <= {"-", ":"}:
                continue
            elements.append(first)

        if not elements:
            raise ShopSpecError(f"{path}: page '{name}' lists no elements")
        if name in pages:
            raise ShopSpecError(f"{path}: duplicate page heading '{name}'")

        pages[name] = Page(
            name=name, route=route_match.group(1), elements=tuple(elements)
        )
    return pages


def _parse_table_body(table_name: str, body: str, path: Path) -> Table:
    columns: list[Column] = []
    constraints: list[Constraint] = []

    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        line = line.rstrip(",").strip()
        if not line:
            continue

        if line.upper().startswith("CONSTRAINT "):
            m = CONSTRAINT_RE.match(line)
            if not m:
                raise ShopSpecError(
                    f"{path}: table '{table_name}' has an unparseable constraint: {line!r}"
                )
            constraints.append(
                Constraint(
                    name=m.group(1),
                    kind=m.group(2).upper(),
                    body=m.group(3).strip(),
                )
            )
        else:
            parts = line.split(None, 1)
            columns.append(
                Column(name=parts[0], sql_type=parts[1].strip() if len(parts) > 1 else "")
            )

    if not columns:
        raise ShopSpecError(f"{path}: table '{table_name}' has no columns")

    return Table(
        name=table_name, columns=tuple(columns), constraints=tuple(constraints)
    )


def parse_schema(path: Path) -> Schema:
    """Parse shop/db/schema.sql into tables, columns, constraints, indexes."""
    text = path.read_text(encoding="utf-8")

    tables: dict[str, Table] = {}
    for m in CREATE_TABLE_RE.finditer(text):
        name = m.group(1)
        if name in tables:
            raise ShopSpecError(f"{path}: table '{name}' created more than once")
        tables[name] = _parse_table_body(name, m.group(2), path)

    if not tables:
        raise ShopSpecError(f"{path}: no CREATE TABLE statements found")

    indexes: dict[str, Index] = {}
    for m in CREATE_INDEX_RE.finditer(text):
        name, table, cols = m.group(1), m.group(2), m.group(3)
        columns = tuple(
            c.strip().split()[0] for c in cols.split(",") if c.strip()
        )
        if name in indexes:
            raise ShopSpecError(f"{path}: index '{name}' created more than once")
        indexes[name] = Index(name=name, table=table, columns=columns)

    return Schema(tables=tables, indexes=indexes)


def naming_violations(schema: Schema) -> list[str]:
    """Constraint and index names that break the documented conventions in
    shop/db/README.md. Returned rather than raised: this is the check the
    db rules reuse, and a rule wants the list, not an exception."""
    problems: list[str] = []
    for table in schema.tables.values():
        for c in table.constraints:
            prefix = CONSTRAINT_PREFIXES[c.kind]
            if not c.name.startswith(prefix):
                problems.append(
                    f"{table.name}.{c.name}: {c.kind} constraint should start with {prefix!r}"
                )
            if not c.name.startswith(f"{prefix}{table.name}"):
                problems.append(
                    f"{table.name}.{c.name}: should be named {prefix}{table.name}_..."
                )
    for i in schema.indexes.values():
        if not i.name.startswith(f"{INDEX_PREFIX}{i.table}"):
            problems.append(
                f"{i.name}: index on {i.table} should be named {INDEX_PREFIX}{i.table}_..."
            )
    return problems


def parse_migrations(migrations_dir: Path) -> tuple[Migration, ...]:
    """Parse shop/db/migrations/. Every file must carry both an up and a
    down section, and the sequence must be contiguous from 0001."""
    migrations: list[Migration] = []

    for p in sorted(migrations_dir.glob("*.sql")):
        m = MIGRATION_FILENAME_RE.match(p.name)
        if not m:
            raise ShopSpecError(
                f"{p}: filename must look like NNNN_snake_case_description.sql"
            )
        text = p.read_text(encoding="utf-8")

        if MIGRATE_UP_MARKER not in text:
            raise ShopSpecError(f"{p}: missing '{MIGRATE_UP_MARKER}' section")
        if MIGRATE_DOWN_MARKER not in text:
            raise ShopSpecError(f"{p}: missing '{MIGRATE_DOWN_MARKER}' section")

        up_start = text.index(MIGRATE_UP_MARKER) + len(MIGRATE_UP_MARKER)
        down_start = text.index(MIGRATE_DOWN_MARKER)
        if down_start < up_start:
            raise ShopSpecError(f"{p}: down section appears before the up section")

        migrations.append(
            Migration(
                number=int(m.group(1)),
                name=m.group(2),
                path=p,
                up=text[up_start:down_start].strip(),
                down=text[down_start + len(MIGRATE_DOWN_MARKER):].strip(),
            )
        )

    if not migrations:
        raise ShopSpecError(f"{migrations_dir}: no migrations found")

    numbers = [m.number for m in migrations]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ShopSpecError(
            f"{migrations_dir}: migration numbers must run 1..N with no gaps; got {numbers}"
        )

    for m in migrations:
        if not m.up:
            raise ShopSpecError(f"{m.path}: up section is empty")
        if not m.down:
            raise ShopSpecError(f"{m.path}: down section is empty")

    return tuple(migrations)


def parse_openapi(path: Path) -> ApiSpec:
    """Scan shop/api/openapi.yaml for path templates, methods and parameter
    names. A line scanner, not a YAML parser -- see the module docstring."""
    lines = path.read_text(encoding="utf-8").splitlines()

    operations: dict[tuple[str, str], Operation] = {}
    in_paths = False
    current_path: str | None = None
    current_method: str | None = None
    method_lines: list[str] = []

    def flush() -> None:
        nonlocal current_method, method_lines
        if current_path is not None and current_method is not None:
            block = "\n".join(method_lines)
            params = tuple(OPENAPI_PARAM_NAME_RE.findall(block))
            operations[(current_path, current_method)] = Operation(
                path=current_path, method=current_method, parameters=params
            )
        current_method = None
        method_lines = []

    for line in lines:
        if not in_paths:
            if line.rstrip() == "paths:":
                in_paths = True
            continue

        # A new top-level key ends the paths section.
        if OPENAPI_TOP_LEVEL_RE.match(line):
            flush()
            break

        path_match = OPENAPI_PATH_RE.match(line)
        if path_match:
            flush()
            current_path = path_match.group(1)
            continue

        method_match = OPENAPI_METHOD_RE.match(line)
        if method_match:
            flush()
            current_method = method_match.group(1)
            continue

        if current_method is not None:
            method_lines.append(line)

    flush()

    if not operations:
        raise ShopSpecError(f"{path}: no operations found under 'paths:'")

    return ApiSpec(operations=operations)
