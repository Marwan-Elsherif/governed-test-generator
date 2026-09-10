"""db rules DB-01..DB-09, and the db notion of target state for C-07.

DB-10 is the forbidden-term list; it is enforced by C-05.
"""
from __future__ import annotations

import re
from typing import Iterable

from govlib import conventions as C
from govlib.rules import FAIL, Context, Finding, Rule

TITLE_RE = re.compile(r"^DB (\w+) - (.+)$")
TABLE_TAG_RE = re.compile(r"^@table-(\w+)$")
MIGRATION_TAG_RE = re.compile(r"^@migration-(\d{4}_[a-z0-9_]+)$")
MIGRATION_ID_RE = re.compile(r"^(\d{4})_([a-z0-9_]+)$")
BACKGROUND_STEP_RE = re.compile(r'^the database schema is at migration "(\d{4}_[a-z0-9_]+)"$')
# The word boundary matters: without it, the "on" inside 'migration "0003_x"'
# matches and a migration id gets checked as if it were a table name.
QUOTED_TABLE_RE = re.compile(r'\b(?:in|on|into|from|of) "(\w+)"')
CONSTRAINT_NAME_RE = re.compile(r'constraint "([^"]+)"')
INDEX_NAME_RE = re.compile(r'index "([^"]+)"')
MIGRATION_REF_RE = re.compile(r'migration "([^"]+)"')

WRITE_STEP_RES = (
    re.compile(r'^the following rows exist in "(\w+)":?$'),
    re.compile(r'^migration "(\d{4}_[a-z0-9_]+)" is applied$'),
    re.compile(r'^I insert into "(\w+)":?$'),
    re.compile(r'^I update "(\w+)" setting \w+ to .+ where .+$'),
    re.compile(r'^I delete from "(\w+)" where .+$'),
    re.compile(r'^I apply migration "(\d{4}_[a-z0-9_]+)"$'),
    re.compile(r'^I roll back migration "(\d{4}_[a-z0-9_]+)"$'),
)
APPLY_RE = re.compile(r'^I apply migration "(\d{4}_[a-z0-9_]+)"$')
ROLLBACK_RE = re.compile(r'^I roll back migration "(\d{4}_[a-z0-9_]+)"$')
ABSENCE_RES = (
    re.compile(r'^no constraint "([^"]+)" exists on "(\w+)"$'),
    re.compile(r'^no index "([^"]+)" exists on "(\w+)"$'),
)
ASSERTION_RES = (
    re.compile(r"^the statement succeeds$"),
    re.compile(r'^the statement fails with constraint "([^"]+)"$'),
    re.compile(r"^the migration succeeds$"),
    re.compile(r'^the migration fails with "(.+)"$'),
    re.compile(r'^an? constraint "([^"]+)" exists on "(\w+)"$'),
    re.compile(r'^no constraint "([^"]+)" exists on "(\w+)"$'),
    re.compile(r'^an index "([^"]+)" exists on "(\w+)" \(([^)]*)\)$'),
    re.compile(r'^no index "([^"]+)" exists on "(\w+)"$'),
    re.compile(r'^the row count of "(\w+)" is (\d+)$'),
    re.compile(r'^the rows in "(\w+)" are unchanged$'),
)
NAME_PATTERNS = {
    "chk": re.compile(r"^chk_\w+$"),
    "fk": re.compile(r"^fk_\w+$"),
    "uq": re.compile(r"^uq_\w+$"),
    "pk": re.compile(r"^pk_\w+$"),
    "idx": re.compile(r"^idx_\w+$"),
}


def title_table(ctx: Context) -> str | None:
    m = TITLE_RE.match(ctx.title)
    return m.group(1) if m else None


def is_write_step(text: str) -> bool:
    return any(rx.match(text) for rx in WRITE_STEP_RES)


def migration_tags(ctx: Context) -> list[str]:
    return [m.group(1) for t in ctx.feature_tags if (m := MIGRATION_TAG_RE.match(t))]


def db01_title(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    m = TITLE_RE.match(ctx.title)
    if not m:
        yield Finding("DB-01", FAIL,
                      f"title must read 'DB <table> - <concern>', found {ctx.title!r}",
                      ctx.feature.line)
        return
    if m.group(1) not in ctx.shop.schema.tables:
        yield Finding("DB-01", FAIL,
                      f"{m.group(1)!r} is not a table in the schema", ctx.feature.line)


def db02_feature_tags(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    table = title_table(ctx)
    line = ctx.feature.line
    table_tags = [m.group(1) for t in ctx.feature_tags if (m := TABLE_TAG_RE.match(t))]
    if table and table_tags != [table]:
        yield Finding("DB-02", FAIL,
                      f"feature must carry @table-{table}, found {table_tags or 'none'}", line)

    touches_migration = any(
        APPLY_RE.match(s.text) or ROLLBACK_RE.match(s.text) for s in ctx.parsed.all_steps()
    )
    tags = migration_tags(ctx)
    if touches_migration and not tags:
        yield Finding("DB-02", FAIL,
                      "feature applies or rolls back a migration so must carry "
                      "@migration-<NNNN>_<slug>", line)
    known = set(ctx.shop.migration_ids)
    expected_next = ctx.shop.next_migration_id_number
    for tag in tags:
        if tag in known:
            continue
        number = int(MIGRATION_ID_RE.match(tag).group(1))
        if number != expected_next:
            yield Finding("DB-02", FAIL,
                          f"@migration-{tag} is new, so its number must be {expected_next:04d}, "
                          f"the next in sequence", line)


def db03_background(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    background = ctx.feature.background
    if background is None or not background.steps:
        yield Finding("DB-03", FAIL,
                      'a Background: with first step \'Given the database schema is at '
                      'migration "<NNNN>_<slug>"\' is required', ctx.feature.line)
        return
    first = background.steps[0]
    m = BACKGROUND_STEP_RE.match(first.text)
    if first.effective != "Given" or not m:
        yield Finding("DB-03", FAIL,
                      'first background step must be \'Given the database schema is at '
                      f'migration "<NNNN>_<slug>"\', found {first.full!r}', first.line)
        return
    if m.group(1) not in ctx.shop.migration_ids:
        yield Finding("DB-03", FAIL,
                      f"{m.group(1)!r} is not an existing migration; the background states "
                      "the state before this feature's changes", first.line)


def db04_rollback(ctx: Context) -> Iterable[Finding]:
    for sc in ctx.scenarios:
        writes = [s for s in sc.steps if is_write_step(s.text)]
        if writes and "@rollback" not in sc.tags:
            yield Finding("DB-04", FAIL,
                          f"scenario {sc.name!r} writes data ({writes[0].full!r}) so must "
                          "carry @rollback", sc.line)


def db05_reversibility(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None or not migration_tags(ctx):
        return
    ups = [sc for sc in ctx.scenarios if "@up" in sc.tags]
    downs = [sc for sc in ctx.scenarios if "@down" in sc.tags]
    if not any(any(APPLY_RE.match(s.text) for s in sc.steps) for sc in ups):
        yield Finding("DB-05", FAIL,
                      "a migration feature needs an @up scenario that applies the migration",
                      ctx.feature.line)
    if not downs:
        yield Finding("DB-05", FAIL,
                      "a migration feature needs a @down scenario that rolls the migration back",
                      ctx.feature.line)
        return
    for sc in downs:
        if not any(ROLLBACK_RE.match(s.text) for s in sc.steps):
            yield Finding("DB-05", FAIL,
                          f"@down scenario {sc.name!r} does not roll back a migration", sc.line)
        if not any(
            any(rx.match(s.text) for rx in ABSENCE_RES) for s in sc.steps_of("Then")
        ):
            yield Finding("DB-05", FAIL,
                          f"@down scenario {sc.name!r} must assert the schema object is gone, "
                          'with \'no constraint "..." exists on "..."\' or the index form',
                          sc.line)


def db06_names(ctx: Context) -> Iterable[Finding]:
    tables = ctx.shop.schema.tables
    for step in ctx.parsed.all_steps():
        for table in QUOTED_TABLE_RE.findall(step.text):
            if table not in tables:
                yield Finding("DB-06", FAIL, f"{table!r} is not a table in the schema", step.line)
        for name in CONSTRAINT_NAME_RE.findall(step.text):
            prefix = name.split("_", 1)[0]
            if prefix not in ("chk", "fk", "uq", "pk") or not NAME_PATTERNS.get(
                prefix, re.compile(r"^$")
            ).match(name):
                yield Finding("DB-06", FAIL,
                              f"constraint name {name!r} does not follow chk_/fk_/uq_/pk_"
                              "<table>_<...>", step.line)
        for name in INDEX_NAME_RE.findall(step.text):
            if not NAME_PATTERNS["idx"].match(name):
                yield Finding("DB-06", FAIL,
                              f"index name {name!r} does not follow idx_<table>_<columns>",
                              step.line)
        if step.table:
            owner = next(
                (m.group(1) for rx in WRITE_STEP_RES if (m := rx.match(step.text))
                 and m.group(1) in tables),
                None,
            )
            if owner:
                for column in step.table[0]:
                    if column and not tables[owner].has_column(column):
                        yield Finding("DB-06", FAIL,
                                      f"{owner!r} has no column {column!r}", step.line)


def db07_fixture_ids(ctx: Context) -> Iterable[Finding]:
    for uuid in ctx.uuids():
        if not uuid.startswith(C.RESERVED_UUID_PREFIX):
            yield Finding("DB-07", FAIL,
                          f"{uuid} is outside the reserved test range "
                          f"{C.RESERVED_UUID_PREFIX}XXXXXXXXXXXX")


def db08_step_catalogue(ctx: Context) -> Iterable[Finding]:
    for sc in ctx.scenarios:
        for step in sc.steps_of("When"):
            if not is_write_step(step.text):
                yield Finding("DB-08", FAIL,
                              f"When step is not in the write catalogue: {step.full!r}",
                              step.line)
        for step in sc.steps_of("Then"):
            if not any(rx.match(step.text) for rx in ASSERTION_RES):
                yield Finding("DB-08", FAIL,
                              f"Then step is not in the assertion catalogue: {step.full!r}",
                              step.line)


def db09_scenario_names(ctx: Context) -> Iterable[Finding]:
    table = title_table(ctx)
    for sc in ctx.scenarios:
        head, sep, rest = sc.name.partition(": ")
        if not sep or not rest.strip():
            yield Finding("DB-09", FAIL,
                          f"scenario name must read '<table>: <expectation>', found {sc.name!r}",
                          sc.line)
        elif table and head != table:
            yield Finding("DB-09", FAIL,
                          f"scenario name starts {head!r} but the feature's table is {table!r}",
                          sc.line)


def target_state(ctx: Context) -> tuple[bool, list[str]]:
    """C-07 for db: the specification is schema.sql and the migrations
    folder; the things under test are the constraints, indexes and
    migration ids the feature names."""
    known_constraints = ctx.shop.constraint_names()
    known_indexes = ctx.shop.index_names()
    known_migrations = set(ctx.shop.migration_ids)

    new: set[str] = set()
    for step in ctx.parsed.all_steps():
        for name in CONSTRAINT_NAME_RE.findall(step.text):
            if name not in known_constraints:
                new.add(f"constraint {name}")
        for name in INDEX_NAME_RE.findall(step.text):
            if name not in known_indexes:
                new.add(f"index {name}")
        for mig in MIGRATION_REF_RE.findall(step.text):
            if mig not in known_migrations:
                new.add(f"migration {mig}")
    for tag in migration_tags(ctx):
        if tag not in known_migrations:
            new.add(f"migration {tag}")
    return bool(new), sorted(new)


RULES: tuple[tuple[str, Rule], ...] = (
    ("DB-01", db01_title),
    ("DB-02", db02_feature_tags),
    ("DB-03", db03_background),
    ("DB-04", db04_rollback),
    ("DB-05", db05_reversibility),
    ("DB-06", db06_names),
    ("DB-07", db07_fixture_ids),
    ("DB-08", db08_step_catalogue),
    ("DB-09", db09_scenario_names),
)
