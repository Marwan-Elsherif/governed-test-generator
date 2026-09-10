-- Web shop schema, PostgreSQL 16.
--
-- This file is the current state of the database, rebuilt by applying every
-- migration in shop/db/migrations/ in order. It is checked in so that the
-- schema can be read without replaying migrations; it is never edited by hand.
--
-- Naming conventions are in shop/db/README.md and are enforced in review.

CREATE TABLE products (
    id               UUID         NOT NULL,
    sku              TEXT         NOT NULL,
    name             TEXT         NOT NULL,
    description      TEXT,
    category         TEXT         NOT NULL,
    price_cents      INTEGER      NOT NULL,
    active           BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_products PRIMARY KEY (id),
    CONSTRAINT uq_products_sku UNIQUE (sku),
    CONSTRAINT chk_products_price_cents_non_negative CHECK (price_cents >= 0)
);

CREATE INDEX idx_products_category ON products (category);
CREATE INDEX idx_products_active_created_at ON products (active, created_at DESC);

CREATE TABLE carts (
    id               UUID         NOT NULL,
    status           TEXT         NOT NULL DEFAULT 'open',
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_carts PRIMARY KEY (id),
    CONSTRAINT chk_carts_status CHECK (status IN ('open', 'ordered', 'abandoned'))
);

CREATE INDEX idx_carts_status_updated_at ON carts (status, updated_at);

CREATE TABLE cart_items (
    id               UUID         NOT NULL,
    cart_id          UUID         NOT NULL,
    product_id       UUID         NOT NULL,
    quantity         INTEGER      NOT NULL,
    CONSTRAINT pk_cart_items PRIMARY KEY (id),
    CONSTRAINT fk_cart_items_cart_id FOREIGN KEY (cart_id) REFERENCES carts (id) ON DELETE CASCADE,
    CONSTRAINT fk_cart_items_product_id FOREIGN KEY (product_id) REFERENCES products (id),
    CONSTRAINT uq_cart_items_cart_id_product_id UNIQUE (cart_id, product_id),
    CONSTRAINT chk_cart_items_quantity_positive CHECK (quantity > 0)
);

CREATE INDEX idx_cart_items_cart_id ON cart_items (cart_id);

CREATE TABLE orders (
    id               UUID         NOT NULL,
    order_number     TEXT         NOT NULL,
    customer_id      UUID         NOT NULL,
    cart_id          UUID,
    email            TEXT         NOT NULL,
    shipping_address TEXT         NOT NULL,
    subtotal_cents   INTEGER      NOT NULL,
    tax_cents        INTEGER      NOT NULL,
    total_cents      INTEGER      NOT NULL,
    status           TEXT         NOT NULL DEFAULT 'placed',
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_orders PRIMARY KEY (id),
    CONSTRAINT uq_orders_order_number UNIQUE (order_number),
    CONSTRAINT fk_orders_cart_id FOREIGN KEY (cart_id) REFERENCES carts (id),
    CONSTRAINT chk_orders_status CHECK (status IN ('placed', 'shipped', 'cancelled')),
    CONSTRAINT chk_orders_totals_consistent CHECK (total_cents = subtotal_cents + tax_cents)
);

CREATE TABLE order_items (
    id               UUID         NOT NULL,
    order_id         UUID         NOT NULL,
    product_id       UUID         NOT NULL,
    name             TEXT         NOT NULL,
    quantity         INTEGER      NOT NULL,
    unit_price_cents INTEGER      NOT NULL,
    CONSTRAINT pk_order_items PRIMARY KEY (id),
    CONSTRAINT fk_order_items_order_id FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE,
    CONSTRAINT fk_order_items_product_id FOREIGN KEY (product_id) REFERENCES products (id)
);

CREATE INDEX idx_order_items_order_id ON order_items (order_id);
