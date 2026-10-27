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

Every `apply` and `destroy` is a production change: the owner says go first.

```bash
cd deploy/gcp
cat > prod.tfvars <<'VARS'      # gitignored
project_id               = "dealfinder-prod-<suffix>"
billing_account          = "XXXXXX-XXXXXX-XXXXXX"
supabase_url             = "https://<ref>.supabase.co"
supabase_publishable_key = "sb_publishable_..."
VARS
tofu init
tofu plan -var-file=prod.tfvars
```

The first apply runs in two steps. Cloud Run refuses a revision whose secret has
no version, so the secret gets its first version before the service exists:

```bash
tofu apply -var-file=prod.tfvars -target=google_secret_manager_secret.env -target=google_secret_manager_secret_iam_member.run_reads_env
python ../secrets.py push --project <project_id>        # the keys from the env file, one version
python ../create_login_role.py --project <project_id>   # adds the production DATABASE_URL
tofu apply -var-file=prod.tfvars                        # everything else
```

Later applies are one step. `tofu plan` saying "No changes" is the drift check.

## Teardown

```bash
tofu destroy -var-file=prod.tfvars
```

That removes every resource above, the secret with all its versions included.
Then drop the database role (see `RUNBOOK.md`).
