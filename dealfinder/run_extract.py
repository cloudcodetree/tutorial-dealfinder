"""Extract structured specs from messy, retailer-polluted electronics listings.

Run:  python -m dealfinder.run_extract
(With an OpenAI-compatible client wired in, swap rule_extract for llm_extract.)
"""
from __future__ import annotations

from .extract import rule_extract

# Real retailer-polluted titles from the snapshot — the true brand is in the
# title text, not the (retailer) brand field.
LISTINGS = [
    "Walmart - COWIN SE7 Active Noise Cancelling Headphones Bluetooth",
    "Anker Soundcore Q20i Hybrid Active Noise Cancelling Headphones",
    "Sony WH-1000XM5 Wireless Headphones",
    "SAMSUNG 990 PRO 2TB PCIe 4.0 NVMe M.2 Internal SSD",
    "Apple MacBook Air M2 (Refurbished) 13-inch Laptop",
]


def main() -> None:
    for text in LISTINGS:
        specs = rule_extract(text)
        print(f"• {text}")
        print(f"  → {specs.model_dump_json()}")


if __name__ == "__main__":
    main()
