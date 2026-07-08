// The four badge tokens (bible §9.7) — exact strings, mapping 1:1 to verdicts.
// No synonyms. Parts 14/27/32/33 use these tokens; Playwright selectors key off
// the `data-badge` attribute below.
export type Badge = "DEAL" | "FAIR" | "SUSPICIOUS" | "OVERPRICED";

// Thresholds on deal_pct (percent below the market median):
//   deal_pct >= 60  → SUSPICIOUS  (too-good-to-be-true; likely an accessory /
//                     mislisting — see the $10.75 "Kindle" trap in the bible)
//   deal_pct >= 10  → DEAL        (meaningfully under the market)
//   deal_pct > -10  → FAIR        (roughly at the market median)
//   else            → OVERPRICED  (well above the market)
export function badgeFor(dealPct: number | undefined): Badge {
  const p = dealPct ?? 0;
  if (p >= 60) return "SUSPICIOUS";
  if (p >= 10) return "DEAL";
  if (p > -10) return "FAIR";
  return "OVERPRICED";
}

// §9.7 colours: DEAL green · FAIR neutral · SUSPICIOUS amber · OVERPRICED grey.
const STYLES: Record<Badge, { bg: string; fg: string }> = {
  DEAL: { bg: "#16a34a", fg: "#ffffff" },
  FAIR: { bg: "#e5e7eb", fg: "#111827" },
  SUSPICIOUS: { bg: "#f59e0b", fg: "#111827" },
  OVERPRICED: { bg: "#6b7280", fg: "#ffffff" },
};

export function DealBadge({ dealPct }: { dealPct?: number }) {
  const badge = badgeFor(dealPct);
  const s = STYLES[badge];
  return (
    <span
      data-badge={badge}
      style={{
        display: "inline-block",
        padding: "2px 8px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
        letterSpacing: 0.3,
        background: s.bg,
        color: s.fg,
      }}
    >
      {badge}
    </span>
  );
}
