"""Remove every item's ``image_url`` from a snapshot file, in place.

The teaching snapshot keeps its listings but not their images (spec §2): the
image URLs point at third-party retailers' servers. The file is rewritten with
its own indent, so the diff touches only the ``image_url`` lines. Idempotent.

    python scripts/strip_snapshot_images.py data/snapshots/electronics-2026-07.json
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _indent(text: str) -> int:
    m = re.search(r"\n( +)\S", text)
    return len(m.group(1)) if m else 2


def strip_images(path: Path) -> int:
    """Drop ``image_url`` from every item; returns how many rows changed."""
    path = Path(path)
    text = path.read_text()
    data = json.loads(text)
    items = data["items"] if isinstance(data, dict) else data
    changed = 0
    for item in items:
        if "image_url" in item:
            del item["image_url"]
            changed += 1
    if changed:
        out = json.dumps(data, indent=_indent(text))
        path.write_text(out + "\n" if text.endswith("\n") else out)
    return changed


def main(argv: list[str]) -> int:
    for arg in argv:
        print(f"stripped image_url from {strip_images(Path(arg))} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
