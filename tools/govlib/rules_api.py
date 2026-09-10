"""api rules API-01..API-11 and API-13, and the api notion of target state
for C-07.

API-12 is the forbidden-term list; it is enforced by C-05.
"""
from __future__ import annotations

import re
from typing import Iterable

from govlib import conventions as C
from govlib.rules import AC_TAG_RE, FAIL, WARN, Context, Finding, Rule

TITLE_RE = re.compile(r"^API (GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) (/\S*)$")
METHODS = ("get", "post", "put", "patch", "delete", "head", "options")
BACKGROUND_STEP = "the API is available"
STATUS_TAG_RE = re.compile(r"^@status-(\d{3})$")
STATUS_STEP_RE = re.compile(r"^the response status is (\d{3})$")
REQUEST_STEP_RE = re.compile(r'^I send a ([A-Z]+) request to "([^"]+)"$')
SCENARIO_NAME_RE = re.compile(r"^returns (\d{3}) when \S.*$")
ERROR_CODE_STEP_RE = re.compile(r'^the error code is "([A-Z_]+)"$')
BODY_ASSERTION_RES = (
    re.compile(r'^the response body has "([^"]+)" equal to (.+)$'),
    re.compile(r'^the response body has "([^"]+)" matching (.+)$'),
    re.compile(r"^the response body is empty$"),
    ERROR_CODE_STEP_RE,
)
MONEY_EQUAL_RE = re.compile(r'^the response body has "([^"]+)" equal to (.+)$')
MONEY_FIELDS = {"subtotal", "tax", "total", "price", "unitprice", "linetotal"}
MONEY_VALUE_RE = re.compile(r'^"\d+\.\d{2}"$')
RESPONSE_TIME_RE = re.compile(r"^the response time is under \d+ ms$")
FIXTURE_ID_STEP_RE = re.compile(r'^(?:a|no) \w[\w ]*? exists with id "([^"]+)"(?: .*)?$')
VOLUME_RE = re.compile(r"\d{3,}")


def title_method_path(ctx: Context) -> tuple[str, str] | None:
    m = TITLE_RE.match(ctx.title)
    return (m.group(1), m.group(2)) if m else None


def path_matcher(template: str) -> re.Pattern[str]:
    """Title path template to a matcher for a concrete request path,
    allowing a query string."""
    return re.compile("^" + re.sub(r"\{[^}]+\}", r"[^/?]+", re.escape(template)
                                   .replace(r"\{", "{").replace(r"\}", "}")) + r"(\?.*)?$")


def scenario_status(sc) -> int | None:
    for tag in sc.tags:
        m = STATUS_TAG_RE.match(tag)
        if m:
            return int(m.group(1))
    return None


def api01_title(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    if not TITLE_RE.match(ctx.title):
        yield Finding("API-01", FAIL,
                      "title must read 'API <METHOD> <path>' with the method in upper case, "
                      f"found {ctx.title!r}", ctx.feature.line)


def api02_feature_tags(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    mp = title_method_path(ctx)
    if mp is None:
        return
    expected = f"@{mp[0].lower()}"
    method_tags = [t for t in ctx.feature_tags if t in {f"@{m}" for m in METHODS}]
    if expected not in method_tags:
        yield Finding("API-02", FAIL,
                      f"feature must carry {expected} for {mp[0]}", ctx.feature.line)
    for extra in method_tags:
        if extra != expected:
            yield Finding("API-02", FAIL,
                          f"feature carries {extra} but the title says {mp[0]}", ctx.feature.line)


def api03_background(ctx: Context) -> Iterable[Finding]:
    if ctx.feature is None:
        return
    background = ctx.feature.background
    if background is None or not background.steps:
        yield Finding("API-03", FAIL,
                      f"a Background: with first step 'Given {BACKGROUND_STEP}' is required",
                      ctx.feature.line)
        return
    first = background.steps[0]
    if first.effective != "Given" or first.text != BACKGROUND_STEP:
        yield Finding("API-03", FAIL,
                      f"first background step must be 'Given {BACKGROUND_STEP}', "
                      f"found {first.full!r}", first.line)


def api04_status_tag(ctx: Context) -> Iterable[Finding]:
    for sc in ctx.scenarios:
        tags = [t for t in sc.tags if STATUS_TAG_RE.match(t)]
        if len(tags) != 1:
            yield Finding("API-04", FAIL,
                          f"scenario {sc.name!r} must carry exactly one @status-<code> tag, "
                          f"found {tags or 'none'}", sc.line)
            continue
        code = int(STATUS_TAG_RE.match(tags[0]).group(1))
        asserted = [
            int(m.group(1))
            for step in sc.steps_of("Then")
            if (m := STATUS_STEP_RE.match(step.text))
        ]
        if not asserted:
            yield Finding("API-04", FAIL,
                          f"scenario {sc.name!r} has no 'Then the response status is <code>' step",
                          sc.line)
        elif code not in asserted:
            yield Finding("API-04", FAIL,
                          f"scenario {sc.name!r} is tagged {tags[0]} but asserts status "
                          f"{asserted[0]}", sc.line)


def api05_one_request(ctx: Context) -> Iterable[Finding]:
    mp = title_method_path(ctx)
    for sc in ctx.scenarios:
        requests = [
            (m, step) for step in sc.steps_of("When")
            if (m := REQUEST_STEP_RE.match(step.text))
        ]
        others = [s for s in sc.steps_of("When") if not REQUEST_STEP_RE.match(s.text)]
        if len(requests) != 1:
            yield Finding("API-05", FAIL,
                          f"scenario {sc.name!r} must send exactly one request with "
                          '\'When I send a <METHOD> request to "<path>"\', found '
                          f"{len(requests)}", sc.line)
        for step in others:
            yield Finding("API-05", FAIL,
                          f"unexpected When step in {sc.name!r}: {step.full!r}", step.line)
        if mp and requests:
            m, step = requests[0]
            method, path = m.groups()
            if method != mp[0]:
                yield Finding("API-05", FAIL,
                              f"request uses {method} but the feature is {mp[0]}", step.line)
            if not path_matcher(mp[1]).match(path):
                yield Finding("API-05", FAIL,
                              f"request path {path!r} does not match the feature path "
                              f"{mp[1]!r}", step.line)


def api06_body_assertion(ctx: Context) -> Iterable[Finding]:
    for sc in ctx.scenarios:
        then_steps = sc.steps_of("Then")
        if not any(
            any(rx.match(step.text) for rx in BODY_ASSERTION_RES) for step in then_steps
        ):
            yield Finding("API-06", FAIL,
                          f"scenario {sc.name!r} asserts nothing about the response body",
                          sc.line)
        status = scenario_status(sc)
        if status is not None and 400 <= status < 500:
            codes = [
                m.group(1) for step in then_steps
                if (m := ERROR_CODE_STEP_RE.match(step.text))
            ]
            if not codes:
                yield Finding("API-06", FAIL,
                              f"scenario {sc.name!r} is a {status} but does not assert "
                              'an error code with \'the error code is "<CODE>"\'', sc.line)
            for code in codes:
                if code not in ctx.shop.error_codes:
                    yield Finding("API-06", FAIL,
                                  f"{code!r} is not in the error code catalogue", sc.line)


def api07_order(ctx: Context) -> Iterable[Finding]:
    codes = [(sc, scenario_status(sc)) for sc in ctx.scenarios]
    known = [(sc, c) for sc, c in codes if c is not None]
    for (prev_sc, prev), (sc, code) in zip(known, known[1:]):
        if code < prev:
            yield Finding("API-07", FAIL,
                          f"scenario {sc.name!r} ({code}) comes after {prev_sc.name!r} "
                          f"({prev}); scenarios run in ascending status order", sc.line)


def api08_scenario_names(ctx: Context) -> Iterable[Finding]:
    for sc in ctx.scenarios:
        m = SCENARIO_NAME_RE.match(sc.name)
        if not m:
            yield Finding("API-08", FAIL,
                          f"scenario name must read 'returns <code> when <condition>', "
                          f"found {sc.name!r}", sc.line)
            continue
        status = scenario_status(sc)
        if status is not None and int(m.group(1)) != status:
            yield Finding("API-08", FAIL,
                          f"scenario {sc.name!r} names {m.group(1)} but is tagged "
                          f"@status-{status}", sc.line)


def api09_money(ctx: Context) -> Iterable[Finding]:
    for step in ctx.parsed.all_steps():
        m = MONEY_EQUAL_RE.match(step.text)
        if not m:
            continue
        field = re.split(r"[.\[\]]", m.group(1).rstrip("]"))[-1].lower()
        if field in MONEY_FIELDS and not MONEY_VALUE_RE.match(m.group(2).strip()):
            yield Finding("API-09", FAIL,
                          f"money value for {field!r} must be a quoted two-decimal string "
                          f'like "19.99", found {m.group(2).strip()!r}', step.line)


def api10_timing(ctx: Context) -> Iterable[Finding]:
    for sc in ctx.scenarios:
        asserts_time = any(RESPONSE_TIME_RE.match(s.text) for s in sc.steps_of("Then"))
        tagged = "@nfr" in sc.tags
        if asserts_time and not tagged:
            yield Finding("API-10", FAIL,
                          f"scenario {sc.name!r} asserts a response time so must carry @nfr",
                          sc.line)
        if tagged and not asserts_time:
            yield Finding("API-10", FAIL,
                          f"scenario {sc.name!r} is @nfr but asserts no response time with "
                          "'the response time is under <n> ms'", sc.line)
        if tagged and not any(VOLUME_RE.search(s.text) for s in sc.steps_of("Given")):
            yield Finding("API-10", FAIL,
                          f"scenario {sc.name!r} is @nfr but no Given step states the data "
                          "volume as a number of at least three digits", sc.line)


def api11_fixtures(ctx: Context) -> Iterable[Finding]:
    for step in ctx.parsed.all_steps():
        if step.effective == "Given" and "exists with id" in step.text:
            if not FIXTURE_ID_STEP_RE.match(step.text):
                yield Finding("API-11", FAIL,
                              'a fixture step must read \'a <thing> exists with id "<uuid>"\' '
                              f'or \'no <thing> exists with id "<uuid>"\', found {step.full!r}',
                              step.line)
    for uuid in ctx.uuids():
        if not uuid.startswith(C.RESERVED_UUID_PREFIX):
            yield Finding("API-11", FAIL,
                          f"{uuid} is outside the reserved test range "
                          f"{C.RESERVED_UUID_PREFIX}XXXXXXXXXXXX")


HTTP_METHOD_WORD_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\b")


def api13_ac_method_match(ctx: Context) -> Iterable[Finding]:
    """A @ac-<n> tag proves a scenario is *linked* to a criterion (C-06); it
    proves nothing about whether the scenario actually tests what that
    criterion says. Found live: a ticket whose AC-2 read "a subsequent GET
    ... returns 404" was covered by a scenario that sent a DELETE. C-06 was
    satisfied (the tag was there) and the file validated ALL PASS; only
    reading the ticket text next to the scenario caught the mismatch.

    This checks one narrow, cheap signal -- when the criterion names an HTTP
    method, does the covering scenario's own request use that method -- as a
    heuristic, not a proof of correctness in general. WARN, not FAIL: it is
    one word matched against one word, not an understanding of what the
    criterion means. Uppercase-only match (GET, not "get the response") to
    keep false positives rare.
    """
    if ctx.ticket is None:
        return
    for sc in ctx.scenarios:
        methods = [
            m.group(1) for step in sc.steps_of("When")
            if (m := REQUEST_STEP_RE.match(step.text))
        ]
        if not methods:
            continue
        for tag in sc.tags:
            ac_match = AC_TAG_RE.match(tag)
            if not ac_match or ac_match.group(1) == "extra":
                continue
            n = int(ac_match.group(1))
            if not (1 <= n <= ctx.ticket.ac_count):
                continue
            ac_text = ctx.ticket.ac(n)
            named = set(HTTP_METHOD_WORD_RE.findall(ac_text))
            if named and methods[0] not in named:
                yield Finding(
                    "API-13", WARN,
                    f"scenario {sc.name!r} is tagged @ac-{n}, whose text names "
                    f"{'/'.join(sorted(named))} but the scenario sends {methods[0]}: "
                    f"{ac_text!r} -- check this scenario actually tests that criterion",
                    sc.line,
                )


def target_state(ctx: Context) -> tuple[bool, list[str]]:
    """C-07 for api: the specification is openapi.yaml, the thing under
    test is the title's method and path."""
    mp = title_method_path(ctx)
    if mp is None:
        return False, []
    method, path = mp
    if ctx.shop.api.has(method, path):
        return False, []
    return True, [f"{method} {path}"]


RULES: tuple[tuple[str, Rule], ...] = (
    ("API-01", api01_title),
    ("API-02", api02_feature_tags),
    ("API-03", api03_background),
    ("API-04", api04_status_tag),
    ("API-05", api05_one_request),
    ("API-06", api06_body_assertion),
    ("API-07", api07_order),
    ("API-08", api08_scenario_names),
    ("API-09", api09_money),
    ("API-10", api10_timing),
    ("API-11", api11_fixtures),
    ("API-13", api13_ac_method_match),
)
