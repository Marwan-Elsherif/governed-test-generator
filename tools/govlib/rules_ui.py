"""ui rules UI-01..UI-08, and the ui notion of target state for C-07.

UI-09 is the forbidden-term list; it is enforced by C-05, which reads the
list out of `conventions/ui.md` and names UI-09 in its findings.
"""
from __future__ import annotations

import re
from typing import Iterable

from govlib.rules import FAIL, Context, Finding, Rule

TITLE_RE = re.compile(r"^UI - (.+?) - (.+)$")
BACKGROUND_STEP_RE = re.compile(r'^I am on the "(.+?)" page$')
PAGE_REF_RE = re.compile(r'the "([^"]+)" page')
ELEMENT_REF_RE = re.compile(r'(?<!the text )the "([^"]+)"(?! page)')

INTERACTION_VERBS = (
    "click", "select", "enter", "clear", "choose", "submit",
    "open", "remove", "set", "type", "navigate to",
)
ASSERTION_PREFIXES = (
    "I should see", "I should not see", "I should be on the",
    "the URL should contain", "the URL should not contain",
    "the page should not reload",
)
STORY_PREFIXES = ("As a shopper", "I want ", "So that ")


def title_page(ctx: Context) -> str | None:
    m = TITLE_RE.match(ctx.title)
    return m.group(1) if m else None


def ui01_title(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    m = TITLE_RE.match(ctx.title)
    if not m:
        yield Finding("UI-01", FAIL,
                      f"title must read 'UI - <Page> - <capability>', found {ctx.title!r}",
                      ctx.feature.line)
        return
    page = m.group(1)
    if page not in ctx.shop.pages:
        yield Finding("UI-01", FAIL,
                      f"{page!r} is not a page in the registry", ctx.feature.line)


def ui02_user_story(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    description = [d for d in ctx.feature.description if d]
    if len(description) < 3:
        yield Finding("UI-02", FAIL,
                      "the three lines under the feature line must be the user story "
                      "'As a shopper' / 'I want ...' / 'So that ...'", ctx.feature.line)
        return
    for got, want in zip(description[:3], STORY_PREFIXES):
        if not got.startswith(want.strip()) or (want.endswith(" ") and got.strip() == want.strip()):
            yield Finding("UI-02", FAIL,
                          f"user story line should start {want.strip()!r}, found {got!r}",
                          ctx.feature.line)


def ui03_background(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    background = ctx.feature.background
    if background is None or not background.steps:
        yield Finding("UI-03", FAIL,
                      'a Background: with first step \'Given I am on the "<Page>" page\' is required',
                      ctx.feature.line)
        return
    first = background.steps[0]
    m = BACKGROUND_STEP_RE.match(first.text)
    if first.effective != "Given" or not m:
        yield Finding("UI-03", FAIL,
                      f'first background step must be \'Given I am on the "<Page>" page\', '
                      f"found {first.full!r}", first.line)
        return
    expected = title_page(ctx)
    if expected and m.group(1) != expected:
        yield Finding("UI-03", FAIL,
                      f"background is on {m.group(1)!r} but the title names {expected!r}",
                      first.line)


def ui04_scenario_names(ctx: Context) -> Iterable[Finding]:
    for sc in ctx.scenarios:
        if not sc.name.startswith("Shopper ") or len(sc.name.split()) < 3:
            yield Finding("UI-04", FAIL,
                          f"scenario name must start 'Shopper ' and a verb phrase, found {sc.name!r}",
                          sc.line)


def ui05_scenario_tags(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    for sc in ctx.scenarios:
        kinds = [t for t in sc.tags if t in ("@happy-path", "@negative")]
        if len(kinds) != 1:
            yield Finding("UI-05", FAIL,
                          f"scenario {sc.name!r} must carry exactly one of @happy-path or "
                          f"@negative, found {kinds or 'neither'}", sc.line)
    if ctx.scenarios and not any("@smoke" in sc.tags for sc in ctx.scenarios):
        yield Finding("UI-05", FAIL, "no scenario carries @smoke", ctx.feature.line)


def ui06_interactions(ctx: Context) -> Iterable[Finding]:
    for sc in ctx.scenarios:
        for step in sc.steps_of("When"):
            text = step.text
            if not text.startswith("I "):
                yield Finding("UI-06", FAIL,
                              f"a When step must start 'I ' and an interaction verb: {step.full!r}",
                              step.line)
                continue
            rest = text[2:]
            if not any(rest.startswith(v + " ") or rest == v for v in INTERACTION_VERBS):
                yield Finding("UI-06", FAIL,
                              f"{step.full!r} does not use an interaction verb "
                              f"({', '.join(INTERACTION_VERBS)})", step.line)


def ui07_assertions(ctx: Context) -> Iterable[Finding]:
    for sc in ctx.scenarios:
        for step in sc.steps_of("Then"):
            if not any(step.text.startswith(p) for p in ASSERTION_PREFIXES):
                yield Finding("UI-07", FAIL,
                              f"a Then step must start with one of "
                              f"{', '.join(repr(p) for p in ASSERTION_PREFIXES)}: {step.full!r}",
                              step.line)


def _referenced(ctx: Context) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """(page references, element references) with line numbers."""
    pages: list[tuple[str, int]] = []
    elements: list[tuple[str, int]] = []
    steps = list(ctx.parsed.all_steps())
    for step in steps:
        for name in PAGE_REF_RE.findall(step.text):
            pages.append((name, step.line))
        # Elements are only extracted from When steps. UI-06 defines
        # `the "<Element>"` as how an *interaction* names its target; UI-07's
        # fixed Then-step catalogue never takes an element as its direct
        # subject (it takes pages, free "text", or a URL literal). Found live:
        # a Then step reading 'products in the "Home & Garden" category'
        # matched the same `the "..."` shape by coincidence of English prose,
        # and got reported as a new page element needing @spec-pending, when
        # it names a filter *value*, not a control. Scoping extraction to
        # When steps removes this without narrowing real element detection,
        # since a genuine element reference has nowhere else to legitimately
        # appear in this domain's fixed grammar.
        if step.effective == "When":
            for name in ELEMENT_REF_RE.findall(step.text):
                elements.append((name, step.line))
    return pages, elements


def ui08_names(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    pages, elements = _referenced(ctx)
    for name, line in pages:
        if name not in ctx.shop.pages:
            yield Finding("UI-08", FAIL, f"{name!r} is not a page in the registry", line)

    page = title_page(ctx)
    if page is None or page not in ctx.shop.pages or ctx.is_spec_pending:
        return
    known = ctx.shop.pages[page]
    for name, line in elements:
        if not known.has_element(name):
            yield Finding("UI-08", FAIL,
                          f"{name!r} is not an element of the {page!r} page; if the ticket "
                          "adds it, tag the feature @spec-pending", line)


def target_state(ctx: Context) -> tuple[bool, list[str]]:
    """C-07 for ui: the specification is the page registry, the things
    under test are the element names the feature refers to."""
    page = title_page(ctx)
    if page is None or page not in ctx.shop.pages:
        return False, []
    known = ctx.shop.pages[page]
    _pages, elements = _referenced(ctx)
    new = sorted({name for name, _ in elements if not known.has_element(name)})
    return bool(new), [f"{page}: {n}" for n in new]


RULES: tuple[tuple[str, Rule], ...] = (
    ("UI-01", ui01_title),
    ("UI-02", ui02_user_story),
    ("UI-03", ui03_background),
    ("UI-04", ui04_scenario_names),
    ("UI-05", ui05_scenario_tags),
    ("UI-06", ui06_interactions),
    ("UI-07", ui07_assertions),
    ("UI-08", ui08_names),
)
