-- Each signed-in user's private saved searches. app.user_id is the verified JWT sub.
SET LOCAL search_path = dealfinder, extensions, public;

CREATE TABLE dealfinder.saved_searches (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    text NOT NULL,
    query      text NOT NULL CHECK (char_length(query) BETWEEN 1 AND 200),
    -- NaN sorts above Infinity in Postgres, so `< 'Infinity'` also rejects NaN.
    max_price  double precision CHECK (max_price IS NULL OR (max_price > 0 AND max_price < 'Infinity')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX saved_searches_user_idx ON dealfinder.saved_searches (user_id, created_at DESC);
ALTER TABLE dealfinder.saved_searches ENABLE ROW LEVEL SECURITY;
ALTER TABLE dealfinder.saved_searches FORCE ROW LEVEL SECURITY;
CREATE POLICY saved_search_owner ON dealfinder.saved_searches
    USING (user_id = current_setting('app.user_id', true))
    WITH CHECK (user_id = current_setting('app.user_id', true));
GRANT SELECT, INSERT, UPDATE, DELETE ON dealfinder.saved_searches TO dealfinder_app;
