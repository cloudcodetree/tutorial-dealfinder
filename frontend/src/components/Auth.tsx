import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase, supabaseConfigured } from "../lib/supabase";
import { fetchMe, type Me } from "../api";

/**
 * Auth (Part 28) — Supabase sign in / session / sign out.
 *
 * On an active session we call the protected GET /me with the session's access
 * token and show the verified identity; a "pro" affordance is gated by the
 * user's role (from the JWT's app-level claim, surfaced by the backend).
 *
 * Needs the learner's OWN Supabase project keys (VITE_SUPABASE_URL /
 * VITE_SUPABASE_ANON_KEY). Without them this panel explains that auth is off and
 * the app runs anonymously — public search still works.
 */
export function Auth({ onSession }: { onSession?: (s: Session | null) => void }) {
  const [session, setSession] = useState<Session | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      onSession?.(data.session);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_evt, s) => {
      setSession(s);
      onSession?.(s);
    });
    return () => sub.subscription.unsubscribe();
  }, [onSession]);

  // Whenever we have a session, verify it against the backend's /me route.
  useEffect(() => {
    if (!session) {
      setMe(null);
      return;
    }
    let cancelled = false;
    fetchMe(session.access_token)
      .then((m) => !cancelled && setMe(m))
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [session]);

  async function signIn(e: React.FormEvent) {
    e.preventDefault();
    if (!supabase) return;
    setBusy(true);
    setError(null);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) setError(error.message);
    setBusy(false);
  }

  async function signOut() {
    await supabase?.auth.signOut();
    setMe(null);
  }

  if (!supabaseConfigured) {
    return (
      <div style={panel}>
        <strong>Auth is off.</strong> Set <code>VITE_SUPABASE_URL</code> and{" "}
        <code>VITE_SUPABASE_ANON_KEY</code> (your Supabase project) to enable sign-in and the{" "}
        <code>/me</code> identity. Public search works without it.
      </div>
    );
  }

  if (session && me) {
    const isPro = me.role === "pro";
    return (
      <div style={panel}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            Signed in as <strong>{me.email ?? me.id}</strong>{" "}
            <span
              style={{
                fontSize: 12,
                padding: "1px 6px",
                borderRadius: 6,
                background: isPro ? "#16a34a" : "#e5e7eb",
                color: isPro ? "#fff" : "#111827",
              }}
            >
              {me.role}
            </span>
          </div>
          <button onClick={signOut} style={linkBtn}>
            Sign out
          </button>
        </div>
        {isPro ? (
          <div style={{ marginTop: 8, fontSize: 13, color: "#16a34a" }}>
            Pro features unlocked (higher search quota, exports).
          </div>
        ) : (
          <div style={{ marginTop: 8, fontSize: 13, color: "#6b7280" }}>
            Free plan. Upgrade to Pro for a higher search quota.
          </div>
        )}
      </div>
    );
  }

  return (
    <form onSubmit={signIn} style={panel}>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <input
          type="email"
          aria-label="Email"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          style={input}
        />
        <input
          type="password"
          aria-label="Password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          style={input}
        />
        <button type="submit" disabled={busy} style={primaryBtn}>
          {busy ? "…" : "Sign in"}
        </button>
      </div>
      {error && <div style={{ marginTop: 8, color: "#dc2626", fontSize: 13 }}>{error}</div>}
    </form>
  );
}

const panel: React.CSSProperties = {
  padding: "12px 14px",
  border: "1px solid #e5e7eb",
  borderRadius: 10,
  background: "#f9fafb",
  fontSize: 14,
  marginBottom: 16,
};
const input: React.CSSProperties = {
  padding: "8px 10px",
  borderRadius: 8,
  border: "1px solid #d1d5db",
  fontSize: 14,
};
const primaryBtn: React.CSSProperties = {
  padding: "8px 16px",
  borderRadius: 8,
  border: "none",
  background: "#2563eb",
  color: "#fff",
  fontWeight: 600,
  cursor: "pointer",
};
const linkBtn: React.CSSProperties = {
  background: "none",
  border: "none",
  color: "#2563eb",
  cursor: "pointer",
  fontSize: 14,
};
