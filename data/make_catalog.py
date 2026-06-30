"""Generate a deterministic synthetic tent catalog with a KNOWN price function.

We invent a ground-truth pricing rule, price most tents by it (plus a little
noise), then inject a handful of underpriced "deals". Because the rule is known,
the tutorial can show the from-scratch model *recovering* it — and the deal
detector catching exactly the tents we marked down.

Run from the repo root:  python data/make_catalog.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

# Ground-truth price = INTERCEPT + TRUE·[capacity, weight_kg, season, brand_tier]
INTERCEPT = 60.0
TRUE = {"capacity": 70.0, "weight_kg": -40.0, "season": 55.0, "brand_tier": 60.0}
BRANDS = [("SummitPro", 3), ("TrailLite", 3), ("BasecampCo", 2),
          ("RidgeRunner", 2), ("ValueOutdoors", 1), ("BudgetTrail", 1)]

rng = np.random.default_rng(42)
N = 28
DEAL_IDS = {3, 9, 17, 24}  # rows we deliberately underprice


def fair_price(cap, wkg, season, tier):
    return (INTERCEPT + TRUE["capacity"] * cap + TRUE["weight_kg"] * wkg
            + TRUE["season"] * season + TRUE["brand_tier"] * tier)


def main() -> None:
    products = []
    for i in range(N):
        cap = int(rng.integers(1, 5))                      # 1–4 person
        wkg = round(float(rng.uniform(0.9, 3.6)), 1)        # 0.9–3.6 kg
        season = int(rng.choice([3, 4]))                    # 3- or 4-season
        brand, tier = BRANDS[int(rng.integers(0, len(BRANDS)))]
        price = fair_price(cap, wkg, season, tier) + float(rng.normal(0, 12))
        if i in DEAL_IDS:
            price *= float(rng.uniform(0.62, 0.78))         # 22–38% under fair
        products.append({
            "id": f"tent-{i:02d}",
            "title": f"{brand} {cap}P {'UL ' if wkg < 1.8 else ''}Tent",
            "brand": brand,
            "category": "tents",
            "price": round(max(price, 39.0), 2),
            "currency": "USD",
            "url": f"https://example.com/tent-{i:02d}",
            "source": "dataset",
            "image_url": None,
            "specs": {"capacity": str(cap), "weight_kg": str(wkg), "season": str(season)},
            "price_history": [],
        })

    out = Path(__file__).parent / "sample" / "catalog.json"
    out.write_text(json.dumps(products, indent=2))
    print(f"wrote {len(products)} tents -> {out.relative_to(Path(__file__).parent.parent)}")


if __name__ == "__main__":
    main()
