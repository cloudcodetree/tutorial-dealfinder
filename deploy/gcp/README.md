# GCP stack (OpenTofu)

Owns DealFinder's Google Cloud resources in one project, all in `us-central1`:
the Cloud Run service `dealfinder-api`, the secret `dealfinder-env` (no value),
the Artifact Registry repo `dealfinder` with its cleanup policies, two service
accounts, GitHub Workload Identity Federation for CI, and a $1 budget alert.
Local state, single operator, the same as the site's `infra/`.

**Does not own:** the image CI deploys (`lifecycle.ignore_changes`), secret
values (`deploy/secrets.py`), the database login role (`deploy/create_login_role.py`),
or anything at Cloudflare (`edge/wrangler.jsonc`).

At launch there are no Cloud Run jobs and no Cloud Scheduler jobs. Best Buy has
not issued a key, so nothing needs scheduling yet (Plan 3, "Launch without Best Buy").

## Use

Run everything from the companion repo root, the folder that holds your `.env`.
Both deploy scripts read `.env` from the current directory and refuse to run
without it. Every `apply`, the migration, both scripts and the merge are
production changes: the owner says go first.

```bash
cat > deploy/gcp/prod.tfvars <<'VARS'      # gitignored
project_id               = "dealfinder-prod-<suffix>"
billing_account          = "XXXXXX-XXXXXX-XXXXXX"
supabase_url             = "https://<ref>.supabase.co"
supabase_publishable_key = "sb_publishable_..."
VARS
tofu -chdir=deploy/gcp init
tofu -chdir=deploy/gcp plan -var-file=prod.tfvars
```

### First deploy, in this order

1. The secret and its access first. Cloud Run refuses a revision whose secret has
   no version, so the service cannot be created yet:
   ```bash
   tofu -chdir=deploy/gcp apply -var-file=prod.tfvars -target=google_secret_manager_secret.env -target=google_secret_manager_secret_iam_member.run_reads_env
   ```
2. The schema, which also creates the `dealfinder_app` and `dealfinder_job` roles.
   `.env` must hold `MIGRATION_DATABASE_URL`, the shared project's admin connection.
   Without it the migrator falls back to `DATABASE_URL`, your local database:
   ```bash
   python -m dealfinder.migrate
   ```
3. The secret's first version, from the keys in `.env` (names printed, never values):
   ```bash
   python deploy/secrets.py push --project <project_id>
   ```
4. The login role and the production `DATABASE_URL`:
   ```bash
   python deploy/create_login_role.py --project <project_id>
   ```
5. Everything else, the Cloud Run service included:
   ```bash
   tofu -chdir=deploy/gcp apply -var-file=prod.tfvars
   ```
6. Point the Worker at the service. Copy `tofu -chdir=deploy/gcp output -raw api_url`
   into `BACKEND_ORIGIN` in `edge/wrangler.jsonc` and commit it on the branch. The
   deploy job refuses to ship the placeholder.
7. The Worker's first deploy, which creates it and its custom domain:
   ```bash
   (cd frontend && npm ci && npm run build) && (cd edge && npm ci && npx wrangler deploy)
   ```
8. The Worker's copy of the edge secret:
   ```bash
   python deploy/secrets.py edge --project <project_id>
   ```
9. The repo variables and the one secret CI deploys with:
   ```bash
   gh variable set GCP_PROJECT --body <project_id>
   gh variable set GCP_WIF_PROVIDER --body "$(tofu -chdir=deploy/gcp output -raw wif_provider)"
   gh variable set GCP_DEPLOY_SA --body "$(tofu -chdir=deploy/gcp output -raw deploy_service_account)"
   gh variable set CLOUDFLARE_ACCOUNT_ID --body <account_id>
   gh secret set CLOUDFLARE_EDGE_TOKEN          # pasted on stdin, never in argv
   ```
10. Merge the branch to `main`. The deploy job builds the image, deploys the
    service and the Worker, then checks `/api/healthz` and `/api/readyz`.

Later applies are one step: `tofu -chdir=deploy/gcp apply -var-file=prod.tfvars`.
`tofu plan` saying "No changes" is the drift check.

## Teardown

```bash
tofu -chdir=deploy/gcp destroy -var-file=prod.tfvars
```

That removes every resource above, the secret with all its versions included.
Then drop the database role (see `RUNBOOK.md`).
