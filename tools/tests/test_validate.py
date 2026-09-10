"""Tests for the Gherkin parser and the rule engine.

The shape of this suite matters as much as its size. For every rule in
every convention document there is a mutation of a valid file that
breaks exactly that rule, and the test asserts that rule id appears in
the failures. That is what makes a passing validation meaningful: not
"nothing was reported", but "each rule has been shown to fire".

A coverage test at the bottom closes the loop by walking the convention
documents and asserting that every rule id they define is exercised
here, so adding a rule to a document without implementing or testing it
fails the build.
"""
import re
from pathlib import Path

import pytest

from govlib import conventions as C
from govlib import gherkin
from govlib import validate as V
from govlib.tickets import parse_all_tickets

ROOT = Path(__file__).resolve().parents[2]
DOMAINS = ("ui", "api", "db")
EXEMPLAR = {
    "ui": ROOT / "features/ui/product_detail_add_to_cart.feature",
    "api": ROOT / "features/api/products_get.feature",
    "db": ROOT / "features/db/products_price_check.feature",
}
TICKETS = parse_all_tickets(ROOT / "tickets")


def exemplar_text(domain: str) -> str:
    return EXEMPLAR[domain].read_text(encoding="utf-8")


def run(domain: str, text: str, *, ticket=None, check_fingerprint=False) -> V.Report:
    return V.validate_feature(
        EXEMPLAR[domain], ROOT, text=text, ticket=ticket,
        domain=domain, check_fingerprint=check_fingerprint,
    )


def mutate(domain: str, *replacements: tuple[str, str], ticket=None) -> V.Report:
    text = exemplar_text(domain)
    for old, new in replacements:
        assert old in text, f"fixture text does not contain {old!r}"
        text = text.replace(old, new, 1)
    return run(domain, text, ticket=ticket)


def failed_rules(report: V.Report) -> set[str]:
    return {f.rule for f in report.failures}


def ticketed_api_text(fingerprint: str | None = None, ticket_id: str = "TKT-2") -> str:
    """The api exemplar rewritten as if it were the output of a run: a
    gov header and a ticket tag instead of @exemplar."""
    fp = fingerprint or C.fingerprint(C.conventions_path(ROOT, "api"))
    text = exemplar_text("api").replace("@api @get @exemplar", f"@api @get @{ticket_id}")
    return f"# gov: ticket={ticket_id} domain=api conventions=api@{fp}\n{text}"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_parser_reads_the_exemplars():
    for domain in DOMAINS:
        parsed = gherkin.parse(EXEMPLAR[domain])
        assert parsed.problems == []
        assert parsed.feature is not None
        assert parsed.feature.background is not None
        assert parsed.feature.scenarios


def test_parser_resolves_and_but_to_the_preceding_keyword():
    parsed = gherkin.parse(Path("x.feature"), (
        "Feature: f\n  Scenario: s\n    Given a\n    And b\n"
        "    When c\n    And d\n    Then e\n    But f\n"
    ))
    effective = [s.effective for s in parsed.feature.scenarios[0].steps]
    assert effective == ["Given", "Given", "When", "When", "Then", "Then"]


def test_parser_attaches_tables_and_docstrings_to_their_step():
    parsed = gherkin.parse(Path("x.feature"), (
        'Feature: f\n  Scenario: s\n    When I insert into "t":\n'
        "      | a | b |\n      | 1 | 2 |\n"
        '    Then x\n      """\n      body\n      """\n'
    ))
    steps = parsed.feature.scenarios[0].steps
    assert steps[0].table == (("a", "b"), ("1", "2"))
    assert steps[1].docstring == "      body"


def test_parser_records_problems_instead_of_raising():
    parsed = gherkin.parse(Path("x.feature"), "Given orphaned step\n")
    assert parsed.feature is None
    assert any("no 'Feature:'" in p for p in parsed.problems)


def test_parser_survives_an_unterminated_docstring():
    parsed = gherkin.parse(Path("x.feature"),
                           'Feature: f\n  Scenario: s\n    When x\n      """\n      open\n')
    assert any("unterminated" in p for p in parsed.problems)


# ---------------------------------------------------------------------------
# The exemplars pass their own rules and fail the other two.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("domain", DOMAINS)
def test_exemplar_passes_its_own_rules(domain):
    report = run(domain, exemplar_text(domain))
    assert report.ok, [str(f) for f in report.failures]
    assert report.warnings == []


@pytest.mark.parametrize("domain", DOMAINS)
def test_exemplar_fails_both_other_rule_sets(domain):
    cross = V.cross_check(EXEMPLAR[domain], ROOT)
    assert set(cross) == set(DOMAINS) - {domain}
    for other, findings in cross.items():
        assert findings, f"{domain} exemplar satisfies the {other} rules"


# ---------------------------------------------------------------------------
# Common rules C-01..C-09.
# ---------------------------------------------------------------------------

def test_c01_rejects_a_file_outside_the_domain_folder(tmp_path):
    stray = tmp_path / "somewhere.feature"
    stray.write_text(exemplar_text("api"), encoding="utf-8")
    report = V.validate_feature(stray, ROOT, domain="api", check_fingerprint=False)
    assert "C-01" in failed_rules(report)


def test_c01_rejects_a_non_snake_case_filename(tmp_path):
    bad = ROOT / "features/api/Products-Get.feature"
    report = V.validate_feature(
        bad, ROOT, domain="api", text=exemplar_text("api"), check_fingerprint=False
    )
    assert "C-01" in failed_rules(report)


def test_c02_accepts_a_correct_header():
    report = run("api", ticketed_api_text(), check_fingerprint=True, ticket=None)
    assert "C-02" not in failed_rules(report)


def test_c02_rejects_a_missing_header():
    text = exemplar_text("api").replace("@api @get @exemplar", "@api @get @TKT-2")
    report = run("api", text, check_fingerprint=True)
    assert "C-02" in failed_rules(report)


def test_c02_rejects_a_wrong_fingerprint():
    report = run("api", ticketed_api_text(fingerprint="deadbeef"), check_fingerprint=True)
    assert any(
        f.rule == "C-02" and "fingerprint" in f.message for f in report.failures
    ), [str(f) for f in report.failures]


def test_c02_rejects_a_header_for_another_domain():
    text = ticketed_api_text().replace("domain=api conventions=api@", "domain=ui conventions=ui@")
    report = run("api", text, check_fingerprint=True)
    assert "C-02" in failed_rules(report)


def test_c02_rejects_a_header_naming_a_different_ticket():
    report = V.validate_feature(
        EXEMPLAR["api"], ROOT, domain="api", text=ticketed_api_text(ticket_id="TKT-9"),
        ticket=TICKETS["TKT-2"], check_fingerprint=True,
    )
    assert "C-02" in failed_rules(report)


def test_c03_flags_a_scenario_with_no_then():
    report = mutate("api", ("    Then the response status is 400\n", ""))
    assert "C-03" in failed_rules(report)


def test_c03_flags_a_given_after_a_when():
    report = mutate("api", (
        '    When I send a GET request to "/products/not-a-uuid"\n',
        '    When I send a GET request to "/products/not-a-uuid"\n'
        '    Given a product exists with id "00000000-0000-4000-8000-000000000999"\n',
    ))
    assert "C-03" in failed_rules(report)


def test_c03_flags_a_second_feature():
    report = mutate("api", ("Feature: API GET /products/{id}",
                            "Feature: API GET /products/{id}\nFeature: another"))
    assert "C-03" in failed_rules(report)


def test_c03_flags_an_outline_with_no_examples():
    report = mutate("api", ("  Scenario: returns 400 when the id is not a UUID",
                            "  Scenario Outline: returns 400 when the id is not a UUID"))
    assert "C-03" in failed_rules(report)


def test_c04_flags_a_missing_domain_tag():
    report = mutate("api", ("@api @get @exemplar", "@get @exemplar"))
    assert "C-04" in failed_rules(report)


def test_c04_flags_another_domains_tag():
    report = mutate("api", ("@api @get @exemplar", "@api @ui @get @exemplar"))
    assert "C-04" in failed_rules(report)


def test_c04_flags_an_exemplar_carrying_a_ticket_tag():
    report = mutate("api", ("@api @get @exemplar", "@api @get @exemplar @TKT-2"))
    assert "C-04" in failed_rules(report)


def test_c04_requires_exactly_one_ticket_tag_on_a_run_output():
    text = ticketed_api_text().replace("@api @get @TKT-2", "@api @get")
    report = run("api", text, check_fingerprint=True)
    assert "C-04" in failed_rules(report)


C05_LEAKS = {
    "ui": ('Then I should see the text "Added to your cart"',
           "Then I should see the status code 200"),
    "api": ("    Given the API is available\n",
            "    Given the API is available\n    And I click the button\n"),
    "db": ('    When I apply migration "0003_products_price_check"',
           "    When I send a request to the endpoint"),
}


@pytest.mark.parametrize("domain", DOMAINS)
def test_c05_catches_cross_domain_vocabulary(domain):
    assert "C-05" in failed_rules(mutate(domain, C05_LEAKS[domain]))


@pytest.mark.parametrize(
    "domain,rule_id", [("ui", "UI-09"), ("api", "API-12"), ("db", "DB-10")]
)
def test_c05_names_the_domain_rule_that_owns_the_ban_list(domain, rule_id):
    """The ban lists are rules in their own right (UI-09, API-12, DB-10) but
    are enforced through C-05, so a finding has to name both."""
    assert C.forbidden_rule_id(ROOT, domain) == rule_id
    report = mutate(domain, C05_LEAKS[domain])
    message = next(f.message for f in report.failures if f.rule == "C-05")
    assert message.startswith(f"{rule_id} forbids")


def test_c05_ignores_comment_lines():
    text = "# gov note: this mentions a constraint and a migration\n" + exemplar_text("ui")
    report = run("ui", text)
    assert "C-05" not in failed_rules(report)


def test_c06_flags_a_scenario_with_no_ac_tag():
    report = mutate("api", ("@status-400 @ac-2", "@status-400"))
    assert "C-06" in failed_rules(report)


def test_c06_flags_uncovered_acceptance_criteria():
    report = run("api", exemplar_text("api"), ticket=TICKETS["TKT-2"])
    assert "C-06" in failed_rules(report)
    assert report.uncovered == [4, 5]


def test_c06_flags_an_out_of_range_ac_tag():
    report = mutate("db", ("@ac-1", "@ac-99"), ticket=TICKETS["TKT-3"])
    assert any("acceptance criteria" in f.message for f in report.failures if f.rule == "C-06")


def test_c06_accepts_full_coverage_and_reports_the_matrix():
    report = mutate(
        "api", ("@status-404 @ac-3", "@status-404 @ac-3 @ac-4 @ac-5"),
        ticket=TICKETS["TKT-2"],
    )
    assert "C-06" not in failed_rules(report)
    assert report.uncovered == []
    assert report.ac_coverage[5] == ["returns 404 when no product has the id"]


def test_c06_accepts_ac_extra():
    report = mutate("db", ("@ac-1", "@ac-extra"), ticket=TICKETS["TKT-3"])
    assert not any("@ac-extra" in f.message for f in report.failures)


def test_c07_requires_spec_pending_for_an_unspecified_endpoint():
    report = mutate("api", ("Feature: API GET /products/{id}",
                            "Feature: API GET /cart/{id}/total"))
    assert "C-07" in failed_rules(report)
    assert any("GET /cart/{id}/total" in f.message for f in report.failures)


def test_c07_rejects_spec_pending_when_everything_is_specified():
    report = mutate("api", ("@api @get @exemplar", "@api @get @exemplar @spec-pending"))
    assert "C-07" in failed_rules(report)


def test_c07_reports_new_objects_as_a_note_when_declared():
    report = mutate(
        "api",
        ("Feature: API GET /products/{id}", "Feature: API GET /cart/{id}/total"),
        ("@api @get @exemplar", "@api @get @exemplar @spec-pending"),
    )
    assert "C-07" not in failed_rules(report)
    assert report.new_objects == ["GET /cart/{id}/total"]


def test_c07_for_ui_counts_unregistered_elements():
    report = mutate("ui", ('the "Add to cart button"', 'the "Buy now button"'))
    assert "C-07" in failed_rules(report)


def test_c07_for_db_counts_new_constraints_and_migrations():
    report = mutate("db", ("0003_products_price_check", "0004_products_new_rule"))
    assert "C-07" in failed_rules(report)


def test_c08_flags_a_duplicate_scenario_name():
    report = mutate("api", ("returns 404 when no product has the id",
                            "returns 400 when the id is not a UUID"))
    assert "C-08" in failed_rules(report)


def test_c08_flags_a_step_repeated_within_one_scenario():
    report = mutate("api", ('    And the error code is "PRODUCT_NOT_FOUND"\n',
                            '    And the error code is "PRODUCT_NOT_FOUND"\n'
                            '    And the error code is "PRODUCT_NOT_FOUND"\n'))
    assert "C-08" in failed_rules(report)


def test_c09_warns_on_an_oversized_scenario():
    padding = "".join(
        f'    And I should see the text "line {n}"\n' for n in range(12)
    )
    report = mutate("ui", ('    Then I should see the text "Added to your cart"\n',
                           '    Then I should see the text "Added to your cart"\n' + padding))
    assert "C-09" in {f.rule for f in report.warnings}
    assert report.ok, "C-09 is a warning, not a failure"


# ---------------------------------------------------------------------------
# ui rules.
# ---------------------------------------------------------------------------

UI_MUTATIONS = {
    "UI-01": ("Feature: UI - Product Detail - Add a product to the cart",
              "Feature: Add a product to the cart"),
    "UI-02": ("  As a shopper\n", ""),
    "UI-03": ('Given I am on the "Product Detail" page',
              'Given I am on the "Cart" page'),
    "UI-04": ("Scenario: Shopper adds a product with the default quantity",
              "Scenario: Adding a product"),
    "UI-05": ("  @happy-path @smoke @ac-1", "  @ac-1"),
    "UI-06": ('When I click the "Add to cart button"',
              'When I hover over the "Add to cart button"'),
    "UI-07": ('Then I should see the text "Added to your cart"',
              'Then the cart contains one item'),
    "UI-08": ('the "Quantity selector"', 'the "Amount picker"'),
}


@pytest.mark.parametrize("rule_id,replacement", sorted(UI_MUTATIONS.items()))
def test_ui_rule_fires(rule_id, replacement):
    assert rule_id in failed_rules(mutate("ui", replacement))


def test_ui05_requires_a_smoke_scenario():
    report = mutate("ui", ("@happy-path @smoke @ac-1", "@happy-path @ac-1"))
    assert any("@smoke" in f.message for f in report.failures if f.rule == "UI-05")


def test_ui08_allows_unregistered_elements_when_spec_pending():
    report = mutate(
        "ui",
        ("@ui @exemplar", "@ui @exemplar @spec-pending"),
        ('the "Quantity selector"', 'the "Amount picker"'),
    )
    assert "UI-08" not in failed_rules(report)


def test_ui08_still_checks_page_names_when_spec_pending():
    report = mutate(
        "ui",
        ("@ui @exemplar", "@ui @exemplar @spec-pending"),
        ('the "Product Listing" page', 'the "Wishlist" page'),
    )
    assert "UI-08" in failed_rules(report)


# ---------------------------------------------------------------------------
# api rules.
# ---------------------------------------------------------------------------

API_MUTATIONS = {
    "API-01": ("Feature: API GET /products/{id}", "Feature: API get /products/{id}"),
    "API-02": ("@api @get @exemplar", "@api @post @exemplar"),
    "API-03": ("Given the API is available", "Given the service is running"),
    "API-04": ("  @status-400 @ac-2", "  @status-418 @ac-2"),
    "API-05": ('When I send a GET request to "/products/not-a-uuid"',
               'When I send a POST request to "/products/not-a-uuid"'),
    "API-06": ('    And the error code is "INVALID_ID_FORMAT"\n', ""),
    "API-07": ("  @status-200 @ac-1", "  @status-500 @ac-1"),
    "API-08": ("Scenario: returns 404 when no product has the id",
               "Scenario: missing product"),
    "API-09": ('And the response body has "$.price" equal to "19.99"',
               'And the response body has "$.price" equal to 19.99'),
    "API-11": ("00000000-0000-4000-8000-000000000101",
               "9f2a7c18-9b4e-4d21-a5f6-0c8e1b2d3a44"),
}


@pytest.mark.parametrize("rule_id,replacement", sorted(API_MUTATIONS.items()))
def test_api_rule_fires(rule_id, replacement):
    assert rule_id in failed_rules(mutate("api", replacement))


def test_api05_flags_a_second_request_in_one_scenario():
    report = mutate("api", (
        '    When I send a GET request to "/products/not-a-uuid"\n',
        '    When I send a GET request to "/products/not-a-uuid"\n'
        '    And I send a GET request to "/products/also-bad"\n',
    ))
    assert "API-05" in failed_rules(report)


def test_api06_flags_an_uncatalogued_error_code():
    report = mutate("api", ('"PRODUCT_NOT_FOUND"', '"NO_SUCH_PRODUCT"'))
    assert "API-06" in failed_rules(report)


def test_api10_fires_both_ways():
    without_tag = mutate("api", (
        "    Then the response status is 200\n",
        "    Then the response status is 200\n    And the response time is under 500 ms\n",
    ))
    assert "API-10" in failed_rules(without_tag)

    without_assertion = mutate("api", ("  @status-200 @ac-1", "  @status-200 @nfr @ac-1"))
    assert "API-10" in failed_rules(without_assertion)


def test_api10_accepts_a_complete_nfr_scenario():
    report = mutate(
        "api",
        ("  @status-200 @ac-1", "  @status-200 @nfr @ac-1"),
        ('    Given a product exists with id "00000000-0000-4000-8000-000000000101" and price "19.99"\n',
         '    Given a product exists with id "00000000-0000-4000-8000-000000000101" and price "19.99"\n'
         "    And the catalogue holds 10000 products\n"),
        ("    Then the response status is 200\n",
         "    Then the response status is 200\n    And the response time is under 500 ms\n"),
    )
    assert "API-10" not in failed_rules(report)


def test_api11_flags_a_malformed_fixture_step():
    report = mutate("api", ('Given a product exists with id "00000000-0000-4000-8000-000000000101" and price "19.99"',
                            'Given the product exists with id "00000000-0000-4000-8000-000000000101"'))
    assert "API-11" in failed_rules(report)


API13_FEATURE = """@api @delete @exemplar
Feature: API DELETE /cart/{id}

  Background:
    Given the API is available

  @status-404 @ac-1
  Scenario: returns 404 when the cart has already been deleted
    When I send a DELETE request to "/cart/00000000-0000-4000-8000-000000000202/total"
    Then the response status is 404
    And the error code is "CART_NOT_FOUND"
"""


def synthetic_ticket(*acceptance_criteria: str):
    from govlib.tickets import Ticket
    return Ticket(id="TKT-999", title="t", description="d",
                 acceptance_criteria=acceptance_criteria, path=ROOT)


def test_api13_warns_on_a_real_method_mismatch():
    """Reproduces exactly what a live run produced: a criterion whose text
    names GET, covered (per its @ac-1 tag) by a scenario that sends DELETE.
    C-06 (the tag exists) and every other rule passed; only this catches
    the mismatch, and only as a warning, not a failure."""
    ticket = synthetic_ticket("A subsequent `GET /cart/{id}` returns 404.")
    report = run("api", API13_FEATURE, ticket=ticket)
    warning = next((f for f in report.warnings if f.rule == "API-13"), None)
    assert warning is not None, [str(f) for f in report.findings]
    assert "GET" in warning.message and "DELETE" in warning.message
    assert "API-13" not in failed_rules(report), "a mismatch is a warning, never a failure"


def test_api13_silent_when_the_method_matches():
    ticket = synthetic_ticket("`DELETE` on an unknown id returns 404.")
    report = run("api", API13_FEATURE, ticket=ticket)
    assert not any(f.rule == "API-13" for f in report.findings)


def test_api13_silent_when_the_criterion_names_no_method():
    """No signal to compare against; must not guess or false-positive."""
    ticket = synthetic_ticket("The cart is gone afterwards.")
    report = run("api", API13_FEATURE, ticket=ticket)
    assert not any(f.rule == "API-13" for f in report.findings)


def test_api13_is_case_sensitive_to_avoid_ordinary_english_false_positives():
    """'get' as an ordinary word ("to get a response") must not be read as
    the HTTP method GET."""
    ticket = synthetic_ticket("The client should get a 404 response back.")
    report = run("api", API13_FEATURE, ticket=ticket)
    assert not any(f.rule == "API-13" for f in report.findings)


# ---------------------------------------------------------------------------
# db rules.
# ---------------------------------------------------------------------------

DB_MUTATIONS = {
    "DB-01": ("Feature: DB products - price_cents must not be negative",
              "Feature: DB widgets - price_cents must not be negative"),
    "DB-03": ('at migration "0002_carts_status"', 'at migration "0099_nonexistent"'),
    "DB-04": ("  @rollback @ac-3", "  @ac-3"),
    "DB-06": ("| price_cents |", "| price_euros |"),
    "DB-08": ("Then the migration succeeds", "Then everything is fine"),
    "DB-09": ("Scenario: products: the down migration removes the constraint",
              "Scenario: orders: the down migration removes the constraint"),
}


@pytest.mark.parametrize("rule_id,replacement", sorted(DB_MUTATIONS.items()))
def test_db_rule_fires(rule_id, replacement):
    assert rule_id in failed_rules(mutate("db", replacement))


def test_db02_requires_the_table_tag():
    report = mutate("db", ("@table-products ", ""))
    assert "DB-02" in failed_rules(report)


def test_db02_requires_a_new_migration_to_take_the_next_number():
    report = mutate("db", ("@migration-0003_products_price_check",
                           "@migration-0007_products_price_check"))
    assert "DB-02" in failed_rules(report)


def test_db02_accepts_a_new_migration_with_the_next_number():
    report = mutate("db", ("@migration-0003_products_price_check",
                           "@migration-0004_products_price_check"))
    assert "DB-02" not in failed_rules(report)


def test_db05_requires_a_down_scenario():
    text = exemplar_text("db")
    text = text[: text.index("  @down @rollback @ac-4")]
    report = run("db", text)
    assert "DB-05" in failed_rules(report)


def test_db05_requires_the_down_scenario_to_assert_absence():
    # 'Then the migration succeeds' followed by the absence assertion occurs
    # only in the @down scenario; the @up one asserts presence.
    report = mutate("db", (
        '    Then the migration succeeds\n'
        '    And no constraint "chk_products_price_cents_non_negative" exists on "products"\n',
        "    Then the migration succeeds\n",
    ))
    assert "DB-05" in failed_rules(report)


def test_db06_flags_a_constraint_name_breaking_the_pattern():
    report = mutate("db", ('constraint "chk_products_price_cents_non_negative" exists',
                           'constraint "products_price_positive" exists'))
    assert "DB-06" in failed_rules(report)


def test_db07_flags_an_id_outside_the_reserved_range():
    report = mutate("db", ("00000000-0000-4000-8000-000000000001",
                           "11111111-2222-4333-8444-555555555555"))
    assert "DB-07" in failed_rules(report)


# ---------------------------------------------------------------------------
# Reporting, and the loop that keeps documents and tests honest.
# ---------------------------------------------------------------------------

def test_render_report_names_rules_and_coverage():
    report = run("api", exemplar_text("api"), ticket=TICKETS["TKT-2"])
    rendered = V.render_report(report, V.cross_check(EXEMPLAR["api"], ROOT))
    assert "FAIL" in rendered
    assert "C-06" in rendered
    assert "ac-4: NOT COVERED" in rendered
    assert "db: fails" in rendered and "ui: fails" in rendered


def test_render_report_flags_a_cross_check_that_did_not_discriminate():
    rendered = V.render_report(run("api", exemplar_text("api")), {"ui": []})
    assert "do not distinguish these domains" in rendered


def documented_rule_ids() -> set[str]:
    ids: set[str] = set()
    for name in ("common", *DOMAINS):
        text = (ROOT / "conventions" / f"{name}.md").read_text(encoding="utf-8")
        ids.update(re.findall(r"^- \*\*([A-Z]+-\d\d) ", text, re.M))
    return ids


def test_every_documented_rule_is_exercised_by_this_suite():
    """A rule added to a convention document but never implemented or
    tested would otherwise sit there looking enforced."""
    suite = Path(__file__).read_text(encoding="utf-8")
    referenced = set(re.findall(r"[A-Z]+-\d\d", suite))
    # The three forbidden-term rules are enforced through C-05, which
    # names them; they are referenced via that finding's message.
    missing = documented_rule_ids() - referenced
    assert missing == set(), f"documented but untested: {sorted(missing)}"


def test_every_implemented_rule_is_documented():
    implemented = set()
    for module in (V.rules_ui, V.rules_api, V.rules_db):
        implemented.update(rule_id for rule_id, _fn in module.RULES)
    implemented.update(rule_id for rule_id, _fn in V.rules.common_rules(V.rules_ui.target_state))
    assert implemented <= documented_rule_ids()
