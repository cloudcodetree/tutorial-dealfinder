import type { Verdict } from "../api";

const TOKEN: Record<Verdict, string> = { deal: "DEAL", fair: "FAIR", suspicious: "SUSPICIOUS", overpriced: "OVERPRICED" };

/** The backend's verdict, shown as-is. There is no null case: with no verdict the
 *  caller shows no badge, and the browser never derives one. */
export default function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`verdict verdict-${verdict}`} data-badge={TOKEN[verdict]} role="img" aria-label={`Verdict: ${verdict}`}>
      {TOKEN[verdict]}
    </span>
  );
}
