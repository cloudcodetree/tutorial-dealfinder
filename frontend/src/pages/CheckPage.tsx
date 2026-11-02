import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { CheckResponse } from "../api";
import CheckForm from "../components/CheckForm";
import VerdictBadge from "../components/VerdictBadge";
import { useTitle } from "../lib/useTitle";

const money = (n: number) => `$${n.toFixed(2)}`;

function CheckResult({ r }: { r: CheckResponse }) {
  return (
    <div className="check-result-card">
      <p className="checked">
        {r.title} at {money(r.price)}
      </p>
      {r.verdict && <VerdictBadge verdict={r.verdict} />}
      <p className="reason">{r.reason}</p>
      {r.fair != null && <p className="fair">Our fair price ~${Math.round(r.fair)}</p>}
    </div>
  );
}

export default function CheckPage() {
  useTitle("Check a deal");
  const [params] = useSearchParams();
  const [result, setResult] = useState<CheckResponse | null>(null);
  return (
    <>
      <h1>Check a deal</h1>
      <p className="lede">
        Found a price? Enter the product and the price you see. We compare it with our price model's fair price for
        that model.
      </p>
      <CheckForm
        onResult={setResult}
        initialTitle={params.get("title") ?? ""}
        initialPrice={params.get("price") ?? ""}
      />
      <section className="check-result" aria-live="polite" aria-label="Result">
        {result && <CheckResult r={result} />}
      </section>
    </>
  );
}
