import { useSearch } from "./api";
import { Auth } from "./components/Auth";
import { SearchBar } from "./components/SearchBar";
import { ResultCard } from "./components/ResultCard";

export default function App() {
  const { results, done, loading, error, transport, search } = useSearch();

  return (
    <main
      style={{
        maxWidth: 760,
        margin: "0 auto",
        padding: "32px 20px",
        fontFamily:
          "system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
        color: "#111827",
      }}
    >
      <header style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 28 }}>DealFinder</h1>
        <p style={{ margin: "4px 0 0", color: "#6b7280" }}>
          Live deal search across sources — results stream in as each source responds.
        </p>
      </header>

      <Auth />

      <SearchBar onSearch={search} loading={loading} />

      {error && (
        <div style={{ color: "#dc2626", marginBottom: 12 }}>
          Search failed: {error}
        </div>
      )}

      {done && (
        <div
          data-testid="search-summary"
          style={{ display: "flex", gap: 16, marginBottom: 12, color: "#374151", fontSize: 14 }}
        >
          <span>
            <strong>{done.count}</strong> offers
          </span>
          <span>
            median <strong>${done.median_price.toFixed(2)}</strong>
          </span>
          {transport === "fetch" && (
            <span style={{ color: "#9ca3af" }}>(fell back to /search)</span>
          )}
        </div>
      )}

      {loading && results.length === 0 && (
        <div style={{ color: "#6b7280" }}>Streaming results…</div>
      )}

      <ul style={{ padding: 0, margin: 0 }}>
        {results.map((r) => (
          <ResultCard key={r.id} result={r} />
        ))}
      </ul>

      {!loading && !error && done && results.length === 0 && (
        <div style={{ color: "#6b7280" }}>No offers found for that query.</div>
      )}
    </main>
  );
}
