# DealFinder infrastructure (Terraform / OpenTofu)

The whole local stack — a Postgres **+ pgvector** database — up or down with one
command.

```bash
cd infra
tofu init                 # one-time
tofu apply -auto-approve  # bring it up
tofu destroy              # tear it all down
```

`tofu output -raw database_url` prints the connection string
(`postgresql://dealfinder:dealfinder@localhost:5433/dealfinder`).

## Colima / non-default Docker socket

If Docker runs via Colima (or anything that isn't `/var/run/docker.sock`), point
the provider at your socket first:

```bash
export DOCKER_HOST=$(docker context inspect -f '{{.Endpoints.docker.Host}}')
tofu apply -auto-approve
```

## Going to the cloud

The app talks to Postgres only through `DATABASE_URL`, so production is a swap,
not a rewrite: point it at a managed Postgres (e.g. a **Supabase pooler** URI,
`...pooler.supabase.com:5432`) and run the same migrations. A cloud stack
(managed DB + app host) lives alongside this one as a second Terraform config.
