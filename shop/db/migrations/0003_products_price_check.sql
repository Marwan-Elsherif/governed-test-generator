-- A pricing import briefly wrote negative prices. Nothing in the schema
-- prevented it. This is the pattern to follow when adding a value constraint
-- to a column that already holds data: verify first, then constrain, so the
-- migration fails loudly rather than silently skipping bad rows.

-- migrate:up
DO $$
DECLARE
    offending_count INTEGER;
BEGIN
    SELECT count(*) INTO offending_count FROM products WHERE price_cents < 0;
    IF offending_count > 0 THEN
        RAISE EXCEPTION
            'Cannot add chk_products_price_cents_non_negative: % existing row(s) have price_cents < 0',
            offending_count;
    END IF;
END $$;

ALTER TABLE products
    ADD CONSTRAINT chk_products_price_cents_non_negative CHECK (price_cents >= 0);

-- migrate:down
ALTER TABLE products DROP CONSTRAINT chk_products_price_cents_non_negative;
