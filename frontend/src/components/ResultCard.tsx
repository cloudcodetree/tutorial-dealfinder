import type { Result } from "../api";
import { DealBadge } from "./DealBadge";

// One offer. Renders the real backend fields: title, price, source, deal_pct,
// plus a DealBadge derived from deal_pct.
export function ResultCard({ result }: { result: Result }) {
  return (
    <li
      data-testid="result-card"
      style={{
        listStyle: "none",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        padding: "12px 14px",
        border: "1px solid #e5e7eb",
        borderRadius: 10,
        marginBottom: 8,
        background: "#fff",
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontWeight: 600,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
          title={result.title}
        >
          {result.title}
        </div>
        <div style={{ fontSize: 13, color: "#6b7280" }}>{result.source}</div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12, flexShrink: 0 }}>
        {typeof result.deal_pct === "number" && (
          <span style={{ fontSize: 13, color: "#6b7280", minWidth: 64, textAlign: "right" }}>
            {result.deal_pct > 0 ? `${result.deal_pct}% under` : `${Math.abs(result.deal_pct)}% over`}
          </span>
        )}
        <DealBadge dealPct={result.deal_pct} />
        <strong style={{ fontVariantNumeric: "tabular-nums", minWidth: 72, textAlign: "right" }}>
          ${result.price.toFixed(2)}
        </strong>
      </div>
    </li>
  );
}
