"""A small, tolerant Gherkin parser.

Tolerant on purpose. A feature file that fails the conventions is exactly
what this tool exists to detect, so the parser must survive malformed
input and hand the rule engine something to report on, rather than
raising and leaving a run with no evidence. Structural problems are
collected in `problems` and surfaced by rule C-03.

Only the subset the conventions use: tags, Feature, Background, Scenario,
Scenario Outline, Examples, steps, docstrings and data tables. No i18n,
no Rule: keyword.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

STEP_RE = re.compile(r"^(\s*)(Given|When|Then|And|But|\*)\s+(\S.*?)\s*$")
TAGS_RE = re.compile(r"^\s*(@\S+(?:\s+@\S+)*)\s*$")
FEATURE_RE = re.compile(r"^\s*Feature:\s*(.*?)\s*$")
BACKGROUND_RE = re.compile(r"^\s*Background:\s*(.*?)\s*$")
SCENARIO_RE = re.compile(r"^\s*(Scenario Outline|Scenario Template|Scenario|Example):\s*(.*?)\s*$")
EXAMPLES_RE = re.compile(r"^\s*(?:Examples|Scenarios):\s*(.*?)\s*$")
TABLE_ROW_RE = re.compile(r"^\s*\|(.*)\|\s*$")
DOCSTRING_RE = re.compile(r'^\s*(""")\s*$')
COMMENT_RE = re.compile(r"^\s*#")

STEP_KEYWORDS = ("Given", "When", "Then")


@dataclass(frozen=True)
class Step:
    keyword: str
    effective: str
    text: str
    line: int
    docstring: str | None = None
    table: tuple[tuple[str, ...], ...] = ()

    @property
    def full(self) -> str:
        return f"{self.keyword} {self.text}"


@dataclass(frozen=True)
class Scenario:
    keyword: str
    name: str
    line: int
    tags: tuple[str, ...] = ()
    steps: tuple[Step, ...] = ()
    examples: tuple[tuple[tuple[str, ...], ...], ...] = ()

    @property
    def is_outline(self) -> bool:
        return self.keyword in ("Scenario Outline", "Scenario Template")

    def steps_of(self, effective: str) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if s.effective == effective)


@dataclass(frozen=True)
class Feature:
    name: str
    line: int
    tags: tuple[str, ...] = ()
    description: tuple[str, ...] = ()
    background: Scenario | None = None
    scenarios: tuple[Scenario, ...] = ()


@dataclass
class ParsedFile:
    path: Path
    text: str
    feature: Feature | None = None
    feature_count: int = 0
    header: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()

    def scannable_text(self) -> str:
        """The file with comment lines removed, as rule C-05 specifies."""
        return "\n".join(l for l in self.lines if not COMMENT_RE.match(l))

    def all_steps(self) -> list[Step]:
        out: list[Step] = []
        if self.feature is None:
            return out
        if self.feature.background:
            out.extend(self.feature.background.steps)
        for sc in self.feature.scenarios:
            out.extend(sc.steps)
        return out


def _split_table_row(raw: str) -> tuple[str, ...]:
    return tuple(cell.strip() for cell in raw.split("|"))


def parse(path: Path, text: str | None = None) -> ParsedFile:
    if text is None:
        text = path.read_text(encoding="utf-8")
    parsed = ParsedFile(path=path, text=text)
    lines = text.splitlines()

    if lines and COMMENT_RE.match(lines[0]):
        parsed.header = lines[0].strip()

    pending_tags: list[str] = []
    feature: dict | None = None
    background: dict | None = None
    scenarios: list[dict] = []
    current: dict | None = None          # background or scenario being filled
    in_description = False
    collecting_examples = False
    i = 0

    def new_scenario(keyword: str, name: str, line: int, tags: list[str]) -> dict:
        return {
            "keyword": keyword, "name": name, "line": line,
            "tags": tuple(tags), "steps": [], "examples": [],
        }

    while i < len(lines):
        raw = lines[i]
        line_no = i + 1
        i += 1

        if not raw.strip() or COMMENT_RE.match(raw):
            continue

        tag_match = TAGS_RE.match(raw)
        if tag_match:
            pending_tags = tag_match.group(1).split()
            continue

        feature_match = FEATURE_RE.match(raw)
        if feature_match:
            parsed.feature_count += 1
            if feature is None:
                feature = {
                    "name": feature_match.group(1), "line": line_no,
                    "tags": tuple(pending_tags), "description": [],
                }
                in_description = True
            else:
                parsed.problems.append(f"line {line_no}: a second 'Feature:' line")
            pending_tags = []
            continue

        background_match = BACKGROUND_RE.match(raw)
        if background_match:
            in_description = False
            collecting_examples = False
            if background is not None:
                parsed.problems.append(f"line {line_no}: a second 'Background:'")
            background = new_scenario("Background", background_match.group(1), line_no, pending_tags)
            current = background
            pending_tags = []
            continue

        scenario_match = SCENARIO_RE.match(raw)
        if scenario_match:
            in_description = False
            collecting_examples = False
            current = new_scenario(
                scenario_match.group(1), scenario_match.group(2), line_no, pending_tags
            )
            scenarios.append(current)
            pending_tags = []
            continue

        if EXAMPLES_RE.match(raw):
            if current is None:
                parsed.problems.append(f"line {line_no}: 'Examples:' outside a scenario")
            else:
                collecting_examples = True
                current["examples"].append([])
            pending_tags = []
            continue

        step_match = STEP_RE.match(raw)
        if step_match:
            in_description = False
            collecting_examples = False
            keyword, body = step_match.group(2), step_match.group(3)
            if current is None:
                parsed.problems.append(f"line {line_no}: step outside a scenario: {raw.strip()!r}")
                continue
            if keyword in STEP_KEYWORDS:
                effective = keyword
            else:
                effective = current["steps"][-1].effective if current["steps"] else "Given"
                if not current["steps"]:
                    parsed.problems.append(
                        f"line {line_no}: '{keyword}' with no preceding step"
                    )
            current["steps"].append(
                Step(keyword=keyword, effective=effective, text=body, line=line_no)
            )
            continue

        table_match = TABLE_ROW_RE.match(raw)
        if table_match:
            row = _split_table_row(table_match.group(1))
            if current is None:
                parsed.problems.append(f"line {line_no}: table row outside a scenario")
            elif collecting_examples and current["examples"]:
                current["examples"][-1].append(row)
            elif current["steps"]:
                last = current["steps"][-1]
                current["steps"][-1] = Step(
                    keyword=last.keyword, effective=last.effective, text=last.text,
                    line=last.line, docstring=last.docstring, table=last.table + (row,),
                )
            else:
                parsed.problems.append(f"line {line_no}: table row with no preceding step")
            continue

        if DOCSTRING_RE.match(raw):
            body_lines: list[str] = []
            closed = False
            while i < len(lines):
                inner = lines[i]
                i += 1
                if DOCSTRING_RE.match(inner):
                    closed = True
                    break
                body_lines.append(inner)
            if not closed:
                parsed.problems.append(f"line {line_no}: unterminated docstring")
            if current and current["steps"]:
                last = current["steps"][-1]
                current["steps"][-1] = Step(
                    keyword=last.keyword, effective=last.effective, text=last.text,
                    line=last.line, docstring="\n".join(body_lines), table=last.table,
                )
            else:
                parsed.problems.append(f"line {line_no}: docstring with no preceding step")
            continue

        if in_description and feature is not None:
            feature["description"].append(raw.strip())
            continue

        parsed.problems.append(f"line {line_no}: unrecognised line: {raw.strip()!r}")

    if feature is None:
        parsed.problems.append("no 'Feature:' line found")
        return parsed

    def finish(d: dict) -> Scenario:
        return Scenario(
            keyword=d["keyword"], name=d["name"], line=d["line"], tags=d["tags"],
            steps=tuple(d["steps"]),
            examples=tuple(tuple(tuple(r) for r in tbl) for tbl in d["examples"]),
        )

    parsed.feature = Feature(
        name=feature["name"],
        line=feature["line"],
        tags=feature["tags"],
        description=tuple(feature["description"]),
        background=finish(background) if background else None,
        scenarios=tuple(finish(s) for s in scenarios),
    )
    return parsed
