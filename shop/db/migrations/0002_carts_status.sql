-- Carts previously had no lifecycle state, so an ordered cart looked identical
-- to one a shopper had abandoned. Adds the status column and its constraint.

-- migrate:up
ALTER TABLE carts ADD COLUMN status TEXT NOT NULL DEFAULT 'open';

ALTER TABLE carts
    ADD CONSTRAINT chk_carts_status CHECK (status IN ('open', 'ordered', 'abandoned'));

CREATE INDEX idx_carts_status_updated_at ON carts (status, updated_at);

-- migrate:down
DROP INDEX idx_carts_status_updated_at;

ALTER TABLE carts DROP CONSTRAINT chk_carts_status;

ALTER TABLE carts DROP COLUMN status;
