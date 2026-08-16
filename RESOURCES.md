# DealFinder — Machine Footprint (disk / RAM / CPU)

**The promise:** the dev stack fits a modest laptop, its footprint is **visible before it
bites**, and it's **reclaimable on demand**. This is the machine-resource sibling of
[COST.md](COST.md): same discipline — *bounded by default, legible, reversible* — applied
to disk and memory instead of dollars.

> Check headroom before any heavy build: `python scripts/disk_check.py`
> Reclaim in one line: `docker system prune -af && docker builder prune -af`

---

## Why disk-full is the dangerous one

When the host disk hits 0, the Docker VM can **corrupt** (containerd/buildkit I/O errors),
not just fail — and it's silent until it happens. The mechanism, specific to Colima
(and most VM-backed Docker on macOS):

- The VM's disk is **thin-provisioned**: the on-host image (`~/.colima`) starts tiny and
  **grows toward its cap, but never shrinks on its own** — even after you delete images.
- The cap can be **larger than the host can afford** (default here: a **100 GiB** cap on a
  228 GiB Mac). So the VM fills the *host* to 0 — and corrupts — long before it thinks
  it's full.
- Heavy images make it worse: the full-ML image (torch + mlflow + prefect) is ~8 GiB to
  build, and re-downloaded models bloat the build cache.

---

## Frugal by default (already wired)

| Mechanism | Effect | Where |
|---|---|---|
| **Light default image** | the always-on stack omits torch/mlflow/prefect | `Dockerfile.dev` |
| **Opt-in full-ML profile** | the heavy image is built only when you ask for it | `docker-compose.full.yml` |
| **Persistent model cache** | the embedding model downloads **once**, not per build | `model_cache` volume |

So the default `docker compose up` is small. You only approach the danger zone if you
build the full-ML image **without headroom**.

## Recommended bounded setup (fresh install)

Give the VM a **ceiling the host can always afford** instead of the 100 GiB default:

```bash
colima start --cpu 4 --memory 4 --disk 40      # bounded, still plenty for the light stack
```

- `--disk 40` is a hard ceiling; the light stack uses a few GiB, the full-ML profile fits
  comfortably, and it can never eat your whole Mac.
- `--memory 4` is the floor for the full-ML profile (the torch MLP OOMs a 2 GiB VM); the
  light stack runs fine on 2 GiB.
- Resizing an existing VM's disk requires recreating it (`colima delete`), which is
  destructive to volumes — so pick the size at first `colima start`, or reclaim (below).

## Prevent the fill

1. **Watch before you build.** `python scripts/disk_check.py` warns when host free drops
   below its floor (default 10 GiB) — a full-ML build (~8 GiB) needs that headroom.
2. **Don't bake heavy into always-on.** Use the light default; opt into the full profile
   only for the ML lessons, and only with headroom.
3. **Let the model cache work** — never delete `model_cache` between builds, or you re-pull.
4. **Prune routinely** (see below) — build cache is the biggest, safest reclaim.

---

## Reclaim (get disk back)

From safest/least-destructive to most:

```bash
# 1. Build cache + dangling images — safe, usually the biggest win (we've reclaimed ~13 GiB).
docker system prune -af && docker builder prune -af

# 2. This stack's containers + volumes (local DB + model cache).
docker compose down -v
docker compose -f docker-compose.yml -f docker-compose.full.yml down -v   # if you used full-ML

# 3. DEEP: recreate the VM to shrink the on-host image (~/.colima) back to ~a couple GiB.
#    DESTRUCTIVE — deletes all Docker data in the VM (volumes included). Back up first,
#    and DON'T do this if other Docker stacks share the same VM.
colima delete && colima start --cpu 4 --memory 4 --disk 40
```

> ⚠ Pruning/`down -v` free space *inside* the VM, but the on-host `~/.colima` image
> doesn't shrink — it just reuses the freed space. Only recreating the VM (step 3) or
> a host-level trim shrinks the file itself. That's why bounding the cap up front matters.

If the VM ever won't start with I/O errors after a fill: `colima restart` runs an fsck on
remount and usually recovers it without data loss (then prune).

---

## Verify you're healthy

- `python scripts/disk_check.py` → `✓ Healthy headroom` (exit 0).
- Host free ≥ your floor (default 10 GiB); the VM disk cap is one the host can afford.
- `docker system df` → build cache isn't dozens of GiB.
