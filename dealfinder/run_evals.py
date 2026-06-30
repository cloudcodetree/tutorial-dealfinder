"""Score the extractor on the golden set and A/B it against a baseline.

Run:  python -m dealfinder.run_evals
"""
from __future__ import annotations

from .evals import ab_compare, brand_only_extract, evaluate
from .extract import rule_extract


def main() -> None:
    rule = evaluate(rule_extract)
    base = evaluate(brand_only_extract)
    print(f"golden set: {rule['n']} cases\n")
    print(f"  rule_extract   exact_match = {rule['exact_match']:.2f}   field_acc = {rule['field_accuracy']:.2f}")
    print(f"  brand_only     exact_match = {base['exact_match']:.2f}   field_acc = {base['field_accuracy']:.2f}")

    ab = ab_compare("rule_extract", rule["field_accuracy"], "brand_only", base["field_accuracy"])
    print(f"\nA/B: winner = {ab['winner']} (+{ab['delta']:.2f} field accuracy)")
    gate = rule["exact_match"] >= 0.90
    print(f"CI gate (exact_match >= 0.90): {'PASS ✓' if gate else 'FAIL ✗'}")


if __name__ == "__main__":
    main()
