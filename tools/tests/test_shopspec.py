"""Tests for tools/govlib/shopspec.py and for the shop/ documents themselves.

Two jobs here. The first half proves the registries parse, so the
validator can cross-reference generated feature files against them. The
second half is more interesting: it pins the deliberate gaps in the
specification.

The shop describes the system as it exists *before* any ticket is
worked. Each ticket then adds something that is genuinely missing. If
someone later "helpfully" fills one of those gaps -- adds the cart total
endpoint to the spec, puts an index on orders.customer_id -- the
corresponding ticket quietly stops making sense and the run that
"passes" against it proves nothing. These tests fail loudly instead.
"""
from pathlib import Path

import pytest

from govlib import shopspec as S

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOP = REPO_ROOT / "shop"
PAGES_PATH = SHOP / "ui" / "pages.md"
SCHEMA_PATH = SHOP / "db" / "schema.sql"
MIGRATIONS_DIR = SHOP / "db" / "migrations"
OPENAPI_PATH = SHOP / "api" / "openapi.yaml"
ERRORS_PATH = SHOP / "api" / "errors.md"
SHOP_README = SHOP / "README.md"
DB_README = SHOP / "db" / "README.md"
JOURNEYS_PATH = SHOP / "ui" / "journeys.md"


# ---------------------------------------------------------------------------
# The registries parse.
# ---------------------------------------------------------------------------

EXPECTED_PAGES = {
    "Product Listing": "/products",
    "Product Detail": "/products/{id}",
    "Cart": "/cart",
    "Checkout": "/checkout",
    "Order Confirmation": "/checkout/confirmation",
}

EXPECTED_TABLES = {
    "products", "carts", "cart_items", "orders", "order_items",
}


def test_pages_parse():
    pages = S.parse_pages(PAGES_PATH)
    assert set(pages) == set(EXPECTED_PAGES)
    for name, route in EXPECTED_PAGES.items():
        assert pages[name].route == route


def test_every_page_lists_elements():
    for page in S.parse_pages(PAGES_PATH).values():
        assert page.elements, f"{page.name} has no elements"
        assert "Element" not in page.elements, "table header leaked into elements"
        assert all(e.strip() for e in page.elements)


@pytest.mark.parametrize(
    "page_name,element",
    [
        ("Product Listing", "Add to cart button"),
        ("Product Listing", "Sort control"),
        ("Product Listing", "Empty results message"),
        ("Product Detail", "Quantity selector"),
        ("Cart", "Cart total"),
        ("Cart", "Empty cart message"),
        ("Checkout", "Place order button"),
        ("Checkout", "Error banner"),
        ("Order Confirmation", "Thank-you heading"),
    ],
)
def test_known_elements_present(page_name, element):
    pages = S.parse_pages(PAGES_PATH)
    assert pages[page_name].has_element(element)


def test_schema_parses():
    schema = S.parse_schema(SCHEMA_PATH)
    assert set(schema.tables) == EXPECTED_TABLES


@pytest.mark.parametrize(
    "table,column",
    [
        ("products", "price_cents"),
        ("products", "category"),
        ("carts", "status"),
        ("carts", "updated_at"),
        ("cart_items", "quantity"),
        ("orders", "customer_id"),
        ("orders", "order_number"),
        ("orders", "subtotal_cents"),
        ("orders", "tax_cents"),
        ("orders", "total_cents"),
        ("order_items", "quantity"),
        ("order_items", "unit_price_cents"),
    ],
)
def test_known_columns_present(table, column):
    schema = S.parse_schema(SCHEMA_PATH)
    assert schema.tables[table].has_column(column)


def test_schema_follows_its_own_naming_conventions():
    """shop/db/README.md documents pk_/fk_/uq_/chk_/idx_ prefixes. The
    schema had better follow them, since db feature files will be checked
    against the same rule."""
    violations = S.naming_violations(S.parse_schema(SCHEMA_PATH))
    assert violations == []


def test_migrations_parse_and_are_all_reversible():
    migrations = S.parse_migrations(MIGRATIONS_DIR)
    assert [m.number for m in migrations] == [1, 2, 3]
    for m in migrations:
        assert m.up, f"{m.path} has an empty up section"
        assert m.down, f"{m.path} has an empty down section"


def test_openapi_parses():
    spec = S.parse_openapi(OPENAPI_PATH)
    assert spec.has("get", "/products")
    assert spec.has("get", "/products/{id}")
    assert spec.has("post", "/cart")
    assert spec.has("get", "/cart/{id}")
    assert spec.has("post", "/cart/{id}/items")
    assert spec.has("patch", "/cart/{id}/items/{itemId}")
    assert spec.has("delete", "/cart/{id}/items/{itemId}")
    assert spec.has("get", "/orders")
    assert spec.has("post", "/orders")
    assert spec.has("get", "/orders/{id}")


# ---------------------------------------------------------------------------
# The deliberate gaps. Each one is what a ticket adds; see the module
# docstring for why these are pinned.
# ---------------------------------------------------------------------------

def test_gap_cart_total_endpoint_does_not_exist():
    """The cart total endpoint is added by a ticket. If it is already in
    the spec, that ticket has nothing to specify."""
    spec = S.parse_openapi(OPENAPI_PATH)
    assert not spec.has("get", "/cart/{id}/total")
    assert "/cart/{id}/total" not in spec.paths


def test_gap_delete_cart_endpoint_does_not_exist():
    """Deleting a whole cart is added by a ticket. Deleting a single cart
    *line* already exists, and the two must not be confused."""
    spec = S.parse_openapi(OPENAPI_PATH)
    assert not spec.has("delete", "/cart/{id}")
    assert spec.has("delete", "/cart/{id}/items/{itemId}")


def test_gap_order_items_quantity_is_unconstrained():
    """A ticket adds a positive-quantity constraint to order_items. The
    equivalent constraint on cart_items already exists and is the naming
    precedent to follow."""
    schema = S.parse_schema(SCHEMA_PATH)
    assert schema.tables["order_items"].checks_on("quantity") == ()

    cart_item_checks = schema.tables["cart_items"].checks_on("quantity")
    assert len(cart_item_checks) == 1
    assert cart_item_checks[0].name == "chk_cart_items_quantity_positive"


def test_gap_orders_customer_id_has_no_index():
    """A ticket adds this index. Indexes on other tables exist, so the
    absence is a gap rather than a convention of the schema."""
    schema = S.parse_schema(SCHEMA_PATH)
    assert schema.indexes_on("orders", "customer_id") == ()
    assert schema.indexes_on("cart_items", "cart_id") != ()


def test_gap_order_listing_is_not_paginated():
    """A ticket adds pagination here. The pagination contract itself
    already exists on the product listing, so the ticket is about applying
    a known contract, not inventing one."""
    spec = S.parse_openapi(OPENAPI_PATH)

    order_list = spec.operations[("/orders", "get")]
    assert "page" not in order_list.parameters
    assert "pageSize" not in order_list.parameters
    assert "customer" in order_list.parameters

    product_list = spec.operations[("/products", "get")]
    assert "page" in product_list.parameters
    assert "pageSize" in product_list.parameters


def test_gap_listing_has_no_filter_controls():
    """A ticket adds category and price filter controls to the storefront.
    The API can already filter (see the products endpoint parameters), so
    that ticket is storefront-only work."""
    listing = S.parse_pages(PAGES_PATH)["Product Listing"]
    element_text = " ".join(listing.elements).lower()
    assert "filter" not in element_text

    product_list = S.parse_openapi(OPENAPI_PATH).operations[("/products", "get")]
    for backend_filter in ("category", "minPrice", "maxPrice"):
        assert backend_filter in product_list.parameters


def test_gap_confirmation_page_shows_no_order_number():
    """A ticket adds the order number and ordered items to this page."""
    confirmation = S.parse_pages(PAGES_PATH)["Order Confirmation"]
    element_text = " ".join(confirmation.elements).lower()
    assert "order number" not in element_text
    assert "ordered items" not in element_text


# ---------------------------------------------------------------------------
# Facts the tickets depend on. A missing fact here means an agent has to
# invent one, and invented facts are exactly what makes a generated
# feature file unreviewable.
# ---------------------------------------------------------------------------

def test_shared_facts_are_specified():
    readme = SHOP_README.read_text(encoding="utf-8")
    assert "21 %" in readme, "the VAT rate a ticket references"
    assert "total = subtotal + tax" in readme
    assert "ORD-2026-000123" in readme, "the order number format"
    assert '"0.00"' in readme, "how zero money is represented"
    assert "00000000-0000-4000-8000" in readme, "the reserved test-data id range"
    assert "400" in readme and "404" in readme, "malformed id versus unknown id"


def test_error_catalogue_covers_the_statuses_tickets_assert():
    errors = ERRORS_PATH.read_text(encoding="utf-8")
    for code in (
        "INVALID_ID_FORMAT",
        "CART_NOT_FOUND",
        "ORDER_NOT_FOUND",
        "CART_EMPTY",
        "VALIDATION_FAILED",
    ):
        assert code in errors, f"{code} is needed to write an error scenario"


def test_pagination_contract_is_specified():
    errors = ERRORS_PATH.read_text(encoding="utf-8")
    assert "pageSize" in errors
    assert "default 20" in errors
    assert "beyond the last" in errors, "how paging past the end behaves"


def test_place_order_contract_is_specified():
    """A ticket asserts 201 with an order number, and 422 with no order
    created, against this endpoint."""
    spec = S.parse_openapi(OPENAPI_PATH)
    assert spec.has("post", "/orders")

    raw = OPENAPI_PATH.read_text(encoding="utf-8")
    place_order_block = raw.split("operationId: placeOrder", 1)[1].split("/orders/{id}", 1)[0]
    assert '"201"' in place_order_block
    assert '"422"' in place_order_block


def test_in_page_update_convention_is_specified():
    """A ticket asserts that applying a filter does not reload the page and
    that the URL reflects it. Sorting and paging already work that way, so
    the expectation is documented rather than invented."""
    journeys = JOURNEYS_PATH.read_text(encoding="utf-8")
    assert "does not reload" in journeys
    assert "query string" in journeys
    assert "sort=price_asc" in journeys


def test_migration_conventions_are_specified():
    """A ticket requires a reversible migration that fails if existing rows
    would violate the new constraint. Both rules, and a worked example, have
    to be findable."""
    db_readme = DB_README.read_text(encoding="utf-8")
    assert "migrate:up" in db_readme
    assert "migrate:down" in db_readme
    assert "Every migration is reversible" in db_readme
    assert "verifying" in db_readme or "verify" in db_readme
    assert "chk_<table>_<column>_<rule>" in db_readme

    reference = (MIGRATIONS_DIR / "0003_products_price_check.sql").read_text(encoding="utf-8")
    assert "RAISE EXCEPTION" in reference, "the verify-then-constrain pattern to copy"


def test_test_data_policy_is_specified():
    db_readme = DB_README.read_text(encoding="utf-8")
    assert "00000000-0000-4000-8000" in db_readme
    assert "rolled back" in db_readme or "transaction" in db_readme


# ---------------------------------------------------------------------------
# Negative tests for the parsers themselves.
# ---------------------------------------------------------------------------

def test_page_without_route_rejected(tmp_path):
    bad = tmp_path / "pages.md"
    bad.write_text("## Some Page\n\n| Element | Kind | Label |\n|---|---|---|\n| x | y | z |\n",
                   encoding="utf-8")
    with pytest.raises(S.ShopSpecError, match="Route"):
        S.parse_pages(bad)


def test_migration_without_down_section_rejected(tmp_path):
    (tmp_path / "0001_thing.sql").write_text("-- migrate:up\nSELECT 1;\n", encoding="utf-8")
    with pytest.raises(S.ShopSpecError, match="migrate:down"):
        S.parse_migrations(tmp_path)


def test_migration_numbering_gap_rejected(tmp_path):
    for name in ("0001_a.sql", "0003_c.sql"):
        (tmp_path / name).write_text(
            "-- migrate:up\nSELECT 1;\n-- migrate:down\nSELECT 2;\n", encoding="utf-8"
        )
    with pytest.raises(S.ShopSpecError, match="no gaps"):
        S.parse_migrations(tmp_path)


def test_naming_violation_is_reported(tmp_path):
    bad = tmp_path / "schema.sql"
    bad.write_text(
        "CREATE TABLE things (\n"
        "    id UUID NOT NULL,\n"
        "    CONSTRAINT things_pkey PRIMARY KEY (id)\n"
        ");\n",
        encoding="utf-8",
    )
    violations = S.naming_violations(S.parse_schema(bad))
    assert violations
    assert "pk_" in violations[0]
