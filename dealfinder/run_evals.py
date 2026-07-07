"""Score the two-signal ranker on the golden set and A/B it against median-only.

Run:  python -m dealfinder.run_evals
"""
from __future__ import annotations

from .evals import (
    GATE_PRECISION,
    ab_compare,
    evaluate,
    median_only_ranker,
    two_signal_ranker,
)


def main() -> None:
    two = evaluate(two_signal_ranker)
    med = evaluate(median_only_ranker)
    print(f"golden set: {two['n']} labeled snapshot items\n")
    print(f"  two_signal   precision@5 = {two['precision_at_5']:.2f}   gate {'PASS ✓' if two['passes_gate'] else 'FAIL ✗'}")
    print(f"  median_only  precision@5 = {med['precision_at_5']:.2f}   gate {'PASS ✓' if med['passes_gate'] else 'FAIL ✗'}")

    ab = ab_compare("two_signal", two["precision_at_5"], "median_only", med["precision_at_5"])
    print(f"\nA/B: winner = {ab['winner']} (+{ab['delta']:.2f} precision@5)")
    print(f"CI gate (precision@5 >= {GATE_PRECISION:.2f}): {'PASS ✓' if two['passes_gate'] else 'FAIL ✗'}")

    print("\ntwo_signal top-5:")
    for t in two["top5"]:
        print(f"  [{t['label']:10}] {t['title'][:60]}")


if __name__ == "__main__":
    main()
