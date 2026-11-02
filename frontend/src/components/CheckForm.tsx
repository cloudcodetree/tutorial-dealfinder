import { useState, type FormEvent } from "react";
import { ApiError, checkDeal, type CheckResponse } from "../api";

// The same limits as the backend's GET /check (serve.CheckTitle and the price Query).
const TITLE_MIN = 3;
const TITLE_MAX = 200;
const PRICE_MAX = 50_000;

type Errors = { title?: string; price?: string };

function validate(title: string, price: string): Errors {
  const errors: Errors = {};
  const t = title.trim();
  if (!t) errors.title = "Enter a product name.";
  else if (t.length < TITLE_MIN) errors.title = `Enter a product name of at least ${TITLE_MIN} characters.`;
  const p = Number(price);
  if (!price.trim() || !Number.isFinite(p) || p <= 0) errors.price = "Enter a price above $0.";
  else if (p > PRICE_MAX) errors.price = "Enter a price up to $50,000.";
  return errors;
}

function messageFor(err: unknown): string {
  if (!(err instanceof ApiError)) return "Something went wrong. Try again.";
  if (err.status === 422) return "Enter a product name and a price above $0.";
  if (err.status === 429) return "Too many checks in a row. Wait a few seconds and try again.";
  return err.detail;
}

interface Props {
  /** Called with the backend's answer, and with null when a new check starts or fails,
   *  so an old verdict never sits beside a new question. */
  onResult(r: CheckResponse | null): void;
  initialTitle?: string;
  initialPrice?: string;
}

export default function CheckForm({ onResult, initialTitle = "", initialPrice = "" }: Props) {
  const [title, setTitle] = useState(initialTitle);
  const [price, setPrice] = useState(initialPrice);
  const [errors, setErrors] = useState<Errors>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    const found = validate(title, price);
    setErrors(found);
    setFailure(null);
    if (found.title || found.price) return;
    onResult(null);
    setBusy(true);
    try {
      onResult(await checkDeal(title.trim(), Number(price)));
    } catch (err) {
      setFailure(messageFor(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="check-form" onSubmit={submit} noValidate aria-busy={busy}>
      <div className="field">
        <label htmlFor="check-title">Product name</label>
        <input
          id="check-title"
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          maxLength={TITLE_MAX}
          autoComplete="off"
          placeholder="e.g. Sony WH-1000XM5"
          aria-invalid={errors.title ? true : undefined}
          aria-describedby={errors.title ? "check-title-error" : undefined}
        />
        {errors.title && <p id="check-title-error" className="field-error">{errors.title}</p>}
      </div>
      <div className="field">
        <label htmlFor="check-price">Price you see (USD)</label>
        <input
          id="check-price"
          type="number"
          inputMode="decimal"
          min="0.01"
          max={PRICE_MAX}
          step="0.01"
          value={price}
          onChange={(e) => setPrice(e.target.value)}
          aria-invalid={errors.price ? true : undefined}
          aria-describedby={errors.price ? "check-price-error" : undefined}
        />
        {errors.price && <p id="check-price-error" className="field-error">{errors.price}</p>}
      </div>
      <button type="submit" className="btn-primary" disabled={busy}>
        {busy ? "Checking…" : "Check"}
      </button>
      {failure && (
        <p className="form-failure" role="alert">
          {failure}
        </p>
      )}
    </form>
  );
}
