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

# 3. DEEP: shrink/bound the Docker DATA DISK. DESTRUCTIVE — wipes all Docker volumes AND
#    images. Back up volumes first (below); don't do this if other stacks share the VM
#    without backing theirs up too.
#
#    GOTCHA (verified 2026-08): Colima keeps Docker data on a SEPARATE persistent disk
#    (~/.colima/_lima/_disks/colima/datadisk). `colima delete` does NOT remove it and
#    `colima start --disk N` REUSES it without resizing — so "delete + start --disk 40"
#    silently leaves the old (e.g. 100 GiB) cap. To actually bound it, remove the datadisk:
docker compose down -v                                    # (+ any other stacks)
mkdir -p ~/vol-backup                                     # back up every volume to keep:
for v in $(docker volume ls -q); do \
  docker run --rm -v "$v":/from alpine tar czf - -C /from . > ~/vol-backup/"$v".tar.gz; done
colima stop && colima delete --force
rm -rf ~/.colima/_lima/_disks/colima                      # the 100 GiB datadisk — the actual fix
colima start --cpu 4 --memory 6 --disk 40                 # fresh datadisk, capped at 40 GiB
docker pull alpine                                        # restore each volume:
for f in ~/vol-backup/*.tar.gz; do v=$(basename "$f" .tar.gz); \
  docker volume create "$v" >/dev/null; \
  docker run --rm -i -v "$v":/to alpine tar xzf - -C /to < "$f"; done
```

> ⚠ Pruning/`down -v` free space *inside* the VM, but the on-host datadisk file doesn't
> shrink — it just reuses the freed space. Only recreating the datadisk (step 3, removing
> `_disks/colima`) shrinks the file and lowers the cap. That's why bounding it up front
> matters — pick `--disk 40` (a size the host can afford) at first `colima start`.

If the VM ever won't start with I/O errors after a fill: `colima restart` runs an fsck on
remount and usually recovers it without data loss (then prune).

---

## Verify you're healthy

- `python scripts/disk_check.py` → `✓ Healthy headroom` (exit 0).
- Host free ≥ your floor (default 10 GiB); the VM disk cap is one the host can afford.
- `docker system df` → build cache isn't dozens of GiB.
