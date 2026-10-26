-- DealFinder's own schema on the shared Supabase project. Nothing here touches
-- another schema's tables. `vector` resolves both locally (fresh install into
-- `extensions`) and on Supabase (already in `extensions`).
CREATE SCHEMA IF NOT EXISTS dealfinder;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
SET LOCAL search_path = dealfinder, extensions, public;

-- The app role. Superusers bypass RLS, so every request-path query runs as this
-- role (db.scoped does SET LOCAL ROLE). It can never log in by itself.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dealfinder_app') THEN
    CREATE ROLE dealfinder_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;
GRANT dealfinder_app TO CURRENT_USER;
GRANT USAGE ON SCHEMA dealfinder TO dealfinder_app;
GRANT USAGE ON SCHEMA extensions TO dealfinder_app;

-- The shared price catalog, isolated per tenant.
CREATE TABLE dealfinder.offers (
    tenant_id  text NOT NULL DEFAULT 'public',
    id         text NOT NULL,
    title      text NOT NULL,
    brand      text,
    source     text NOT NULL,
    price      double precision NOT NULL,
    currency   text DEFAULT 'USD',
    url        text,
    image_url  text,
    embedding  vector(384),
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, id)
);
CREATE INDEX offers_embedding_idx ON dealfinder.offers USING hnsw (embedding vector_cosine_ops);
ALTER TABLE dealfinder.offers ENABLE ROW LEVEL SECURITY;
ALTER TABLE dealfinder.offers FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON dealfinder.offers
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON dealfinder.offers TO dealfinder_app;

-- Each signed-in user's private watchlist. app.user_id is the verified JWT sub.
CREATE TABLE dealfinder.watchlist (
    user_id         text NOT NULL,
    tenant_id       text NOT NULL DEFAULT 'public',
    offer_id        text NOT NULL,
    title           text NOT NULL,
    url             text,
    image_url       text,
    source          text,
    target_price    double precision CHECK (target_price IS NULL OR (target_price > 0 AND target_price < 'Infinity')),
    last_price      double precision NOT NULL,
    last_checked_at timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, offer_id)
);
ALTER TABLE dealfinder.watchlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE dealfinder.watchlist FORCE ROW LEVEL SECURITY;
CREATE POLICY watchlist_owner ON dealfinder.watchlist
    USING (user_id = current_setting('app.user_id', true))
    WITH CHECK (user_id = current_setting('app.user_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON dealfinder.watchlist TO dealfinder_app;
