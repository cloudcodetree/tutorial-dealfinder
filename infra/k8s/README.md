# DealFinder on Kubernetes (Part 25)

Applyable manifests that run the DealFinder FastAPI app in a cluster against a
**managed** Postgres. This is the cloud-native twin of the local Terraform stack
in `../` (Part 24): same container image, same env contract — a different runtime.

## Why a managed Postgres (no DB in-cluster)

We deliberately do **not** run Postgres in the cluster. A stateful database wants
durable storage, backups, failover, and version upgrades — all of which a managed
service (Supabase pooler, Amazon RDS, Neon, Cloud SQL) does better and safer than
a hand-rolled `StatefulSet`. The app only needs a `DATABASE_URL`; where that
Postgres lives is an implementation detail. So the cluster stays **stateless**
(easy to scale, drain, and replace), and the connection string is supplied as a
Secret. Point `DATABASE_URL` at any pgvector-capable managed Postgres and the
same schema/code works — exactly as the Terraform stack notes.

## Files

| File | What it is |
| --- | --- |
| `namespace.yaml` | The `dealfinder` namespace. |
| `configmap.yaml` | Non-secret config (Apify actor, Shopify stores, log level). |
| `secret.example.yaml` | **Template** for the Secret — placeholders only, no real values. |
| `deployment.yaml` | The app Deployment: `envFrom` ConfigMap + Secret, `/healthz` probes, resource requests/limits. |
| `service.yaml` | ClusterIP Service (port 80 → container 8000). |
| `ingress.yaml` | Ingress with TLS + SSE-friendly (buffering off) annotations. |
| `hpa.yaml` | CPU-based HorizontalPodAutoscaler (2→10 pods at 70% CPU). |
| `kustomization.yaml` | Bundles everything except the Secret template. |

## Apply order

The Secret is managed **out-of-band** (see below); everything else applies via
Kustomize:

```bash
# 1. Namespace + workloads (Kustomize creates the namespace first).
kubectl apply -k .

# 2. The Secret — copy the template, fill in real values, apply separately.
cp secret.example.yaml secret.yaml     # secret.yaml is gitignored
$EDITOR secret.yaml
kubectl apply -f secret.yaml

# 3. Restart to pick up the Secret if pods started before it existed.
kubectl -n dealfinder rollout restart deployment/dealfinder-app
kubectl -n dealfinder rollout status  deployment/dealfinder-app
```

Push the image referenced in `deployment.yaml`
(`ghcr.io/cloudcodetree/dealfinder-app`) — built from the repo `Dockerfile` — to
your registry first, and pin it by tag or digest.

## Secrets management

- `secret.example.yaml` contains **placeholders only**. The real, filled-in
  `secret.yaml` is gitignored and must never be committed.
- For anything beyond a demo, don't apply a plaintext Secret by hand. Use a
  secrets operator so the source of truth is your cloud secrets manager, not a
  file:
  - **External Secrets Operator** syncing from AWS Secrets Manager / GCP Secret
    Manager / Vault, or
  - **Sealed Secrets** / **SOPS** for encrypted-at-rest manifests you *can* commit.
- The Secret carries: `DATABASE_URL`, `SUPABASE_JWT_SECRET` (verifies Supabase
  session JWTs — see `dealfinder/auth.py`), the Stripe keys
  (`STRIPE_SECRET_KEY`, `STRIPE_PRICE_PRO`, `STRIPE_WEBHOOK_SECRET` — see
  `dealfinder/billing.py`), and the optional live-source API keys.

## How it maps to the Terraform stack (Part 24)

| Terraform (`infra/main.tf`, Docker provider) | Kubernetes (here) |
| --- | --- |
| `docker_container.app` (image built from `Dockerfile`) | `Deployment` → same image |
| `env = [DATABASE_URL, RAPIDAPI_KEY, …]` on the container | `envFrom` ConfigMap (non-secret) + Secret (secret) |
| `docker_container.db` (local pgvector) | **removed** — replaced by an external managed Postgres via `DATABASE_URL` |
| host port 8000 bound to loopback | `Service` (ClusterIP) + `Ingress` (public, TLS) |
| single container | `replicas: 2` + `HorizontalPodAutoscaler` |
| `healthcheck` on the DB | readiness/liveness probes on the app's `/healthz` |

The env contract is identical, so the app binary doesn't change between the two —
only how it's scheduled and how the database is provided.

## Note on SSE

`GET /search/stream` is Server-Sent Events. The Ingress disables proxy buffering
(`nginx.ingress.kubernetes.io/proxy-buffering: "off"`) and raises the read
timeout so streamed `results` frames reach the browser as they're produced. On a
different ingress controller (ALB, Traefik, …), set the equivalent
no-buffering / long-timeout options.

## Validate the manifests

```bash
# YAML well-formedness (no cluster needed):
python3 -c "import glob,yaml; [list(yaml.safe_load_all(open(f))) for f in glob.glob('*.yaml')]"

# Schema validation against the Kubernetes API (if installed):
kubeconform -strict -summary *.yaml
# or
kubeval *.yaml
```
