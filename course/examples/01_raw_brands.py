# Part 1: the raw `brand` field, straight from the frozen snapshot.
from dealfinder.snapshot import load_snapshot

items = load_snapshot("data/snapshots/electronics-2026-07.json")
print(len(items))

for item in items[:8]:
    print(repr(item["brand"]))
