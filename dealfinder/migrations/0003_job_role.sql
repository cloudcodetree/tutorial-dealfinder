-- The job role. Scheduled jobs (retention purge, page builds, re-pricing) must
-- reach every user's rows, which the request-path policies hide by design.
-- db.job_scope does SET LOCAL ROLE dealfinder_job; this role cannot log in and
-- cannot bypass RLS, so it sees exactly what the job_all policies below grant.
SET LOCAL search_path = dealfinder, extensions, public;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dealfinder_job') THEN
    CREATE ROLE dealfinder_job NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;
GRANT dealfinder_job TO CURRENT_USER;
GRANT USAGE ON SCHEMA dealfinder TO dealfinder_job;
GRANT USAGE ON SCHEMA extensions TO dealfinder_job;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON dealfinder.offers, dealfinder.watchlist, dealfinder.saved_searches TO dealfinder_job;

-- Policies are permissive, so these OR with the per-tenant and per-user ones:
-- the request role still sees only its own rows; the job role sees all of them.
CREATE POLICY job_all ON dealfinder.offers FOR ALL TO dealfinder_job USING (true) WITH CHECK (true);
CREATE POLICY job_all ON dealfinder.watchlist FOR ALL TO dealfinder_job USING (true) WITH CHECK (true);
CREATE POLICY job_all ON dealfinder.saved_searches FOR ALL TO dealfinder_job USING (true) WITH CHECK (true);
