import { createClient, type SupabaseClient } from "@supabase/supabase-js";

// Supabase client for Auth (Part 28). Config comes from Vite env vars — the
// learner supplies their OWN project's URL + anon key (Project Settings → API).
// Without them, `supabase` is null and the app runs anonymously: public search
// still works, only the /me identity + pro affordance are gated off.
const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

export const supabaseConfigured = Boolean(url && anonKey);

export const supabase: SupabaseClient | null = supabaseConfigured
  ? createClient(url as string, anonKey as string)
  : null;
