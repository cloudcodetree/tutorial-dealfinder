import { useState, type FormEvent } from "react";

export function SearchBar({
  onSearch,
  loading,
}: {
  onSearch: (q: string) => void;
  loading: boolean;
}) {
  const [q, setQ] = useState("noise cancelling headphones");

  function submit(e: FormEvent) {
    e.preventDefault();
    onSearch(q);
  }

  return (
    <form onSubmit={submit} style={{ display: "flex", gap: 8, marginBottom: 16 }}>
      <input
        aria-label="Search for a product"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search for a product…"
        style={{
          flex: 1,
          padding: "10px 12px",
          borderRadius: 10,
          border: "1px solid #d1d5db",
          fontSize: 15,
        }}
      />
      <button
        type="submit"
        disabled={loading}
        style={{
          padding: "10px 18px",
          borderRadius: 10,
          border: "none",
          background: loading ? "#93c5fd" : "#2563eb",
          color: "#fff",
          fontWeight: 600,
          cursor: loading ? "default" : "pointer",
        }}
      >
        {loading ? "Searching…" : "Search"}
      </button>
    </form>
  );
}
