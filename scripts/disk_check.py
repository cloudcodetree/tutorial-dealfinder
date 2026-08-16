#!/usr/bin/env python3
"""Disk footprint monitor — see the machine budget BEFORE it bites.

The dev stack's disk-full failure mode is catastrophic (it can corrupt the Docker
VM), and it's silent until 0 bytes free. This reports the real numbers — host free
space, the Colima VM's disk cap, the on-host VM image size, and Docker's
image/cache/volume breakdown — and WARNS while there's still headroom.

Read-only, stdlib-only, cross-platform, and degrades gracefully when Colima/Docker
aren't running. Exit 0 = healthy headroom; 1 = low, reclaim before heavy work.
See RESOURCES.md.

    python scripts/disk_check.py            # default floor: 10 GiB free
    python scripts/disk_check.py --floor 15
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

GREEN, YELLOW, RED, DIM, OFF = "\033[32m", "\033[33m", "\033[31m", "\033[2m", "\033[0m"
GiB = 1024 ** 3


def _run(cmd: list[str], timeout: int = 6) -> str | None:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else None
    except (FileNotFoundError, subprocess.SubprocessError):
        return None


def _floor_gb() -> float:
    if "--floor" in sys.argv:
        try:
            return float(sys.argv[sys.argv.index("--floor") + 1])
        except (IndexError, ValueError):
            pass
    return 10.0


def main() -> int:
    floor = _floor_gb()
    home = os.path.expanduser("~")
    free_gb = shutil.disk_usage(home).free / GiB

    print(f"{DIM}DealFinder disk footprint — the dev-stack machine budget.{OFF}\n")
    color = GREEN if free_gb >= floor else (YELLOW if free_gb >= floor / 2 else RED)
    print(f"  host free space   {color}{free_gb:6.1f} GiB{OFF}   (floor {floor:.0f} GiB)")

    # Colima VM: disk cap + status (the cap can exceed what the host can afford).
    colima = _run(["colima", "list"])
    printed_vm = False
    if colima:
        # columns: PROFILE STATUS ARCH CPUS MEMORY DISK [RUNTIME] [ADDRESS]
        for line in colima.splitlines():
            cols = line.split()
            if len(cols) >= 6 and cols[1] in ("Running", "Stopped"):
                status, disk = cols[1], cols[5]     # DISK is positional (after MEMORY)
                warn = "  ⚠ larger than host — see RESOURCES.md" if disk.rstrip("GiBG").isdigit() and int(disk.rstrip("GiBG")) >= free_gb else ""
                print(f"  colima VM disk    {DIM}cap {disk}, {status}{OFF}{YELLOW}{warn}{OFF}")
                printed_vm = True
                break
    if not printed_vm:
        print(f"  colima VM disk    {DIM}(colima not found / not reporting){OFF}")

    # The actual on-host VM image (grows toward the cap, never shrinks on its own).
    du = _run(["du", "-sh", os.path.join(home, ".colima")], timeout=10)
    if du:
        print(f"  VM image on disk  {DIM}{du.split()[0]} (~/.colima; reclaim by prune or recreate){OFF}")

    # Docker's own breakdown — only if the daemon is up.
    dsd = _run(["docker", "system", "df"])
    if dsd:
        print(f"\n{DIM}  docker system df:{OFF}")
        for line in dsd.splitlines():
            print(f"    {line}")
    else:
        print(f"\n  {DIM}docker daemon not reachable (VM stopped?) — start it to see/reclaim"
              f" image + build-cache usage{OFF}")

    print()
    if free_gb >= floor:
        print(f"{GREEN}✓ Healthy headroom.{OFF} A full-ML image build (~8 GiB) needs the floor free;"
              f" you have room.")
        return 0
    print(f"{RED}⚠ Low disk ({free_gb:.1f} GiB free).{OFF} Reclaim before any heavy build:")
    print(f"  {DIM}docker system prune -af && docker builder prune -af   # cache + dangling (safe){OFF}")
    print(f"  {DIM}docker compose down -v                                # this stack's containers+volumes{OFF}")
    print(f"  {DIM}see RESOURCES.md → Reclaim for the deep option (recreate the VM){OFF}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
