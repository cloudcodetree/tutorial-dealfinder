"""One set of Nocturne tokens: the shopper front end owns them, the lab and the deal
pages copy them, and every text pair meets WCAG AA."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONT = ROOT / "frontend/src/theme/tokens.css"
LAB = ROOT / "dealfinder/static/lab/lab.css"
DEAL = ROOT / "dealfinder/templates/deal.css"


def root_vars(path) -> dict[str, str]:
    """The first :root{...} block as {"--name": "value"}."""
    css = re.sub(r"/\*.*?\*/", "", Path(path).read_text(), flags=re.S)
    block = re.search(r":root\s*\{(.*?)\}", css, re.S).group(1)
    pairs = (decl.split(":", 1) for decl in block.split(";") if ":" in decl)
    return {k.strip(): v.strip() for k, v in pairs if k.strip().startswith("--")}


def contrast(a: str, b: str) -> float:
    """WCAG 2.1 contrast ratio of two #rrggbb colors."""
    def lum(h):
        r, g, bl = (int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (r, g, bl)]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_lab_tokens_match_frontend():
    front, lab = root_vars(FRONT), root_vars(LAB)
    assert {k: v for k, v in lab.items() if front.get(k) != v} == {}


def test_deal_page_tokens_match_frontend():
    if not DEAL.exists():
        pytest.skip("deal pages wait for a Best Buy key (Plan 3 Task 4, deferred)")
    front, deal = root_vars(FRONT), root_vars(DEAL)
    assert {k: v for k, v in deal.items() if front.get(k) != v} == {}


TEXT_PAIRS = [("--color-text", "--color-bg"), ("--color-text", "--color-surface"),
              ("--color-neutral-400", "--color-bg"), ("--color-neutral-500", "--color-bg"),
              ("--color-neutral-500", "--color-surface"), ("--color-accent", "--color-bg"),
              ("--color-accent", "--color-surface")] + \
             [(f"--verdict-{v}-fg", f"--verdict-{v}-bg") for v in ("deal", "fair", "suspicious", "overpriced")]


@pytest.mark.parametrize("fg,bg", TEXT_PAIRS)
def test_text_pairs_meet_wcag_aa(fg, bg):
    t = root_vars(FRONT)
    assert contrast(t[fg], t[bg]) >= 4.5


def test_verdict_pairs_build_on_ok_and_warn():
    t = root_vars(FRONT)
    assert t["--verdict-deal-fg"] == t["--ok"] and t["--verdict-suspicious-fg"] == t["--warn"]


def test_frontend_loads_no_web_fonts():
    files = list((ROOT / "frontend/src").rglob("*.css"))
    assert FRONT in files
    css = "".join(p.read_text() for p in files)
    assert "fonts.googleapis.com" not in css and "@font-face" not in css


def test_base_css_has_focus_ring_sr_only_and_wrapping():
    css = (ROOT / "frontend/src/theme/base.css").read_text()
    assert ":focus-visible" in css and ".sr-only" in css and "overflow-wrap: anywhere" in css
