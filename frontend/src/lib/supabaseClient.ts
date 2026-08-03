// Supabase Auth (Growth Phase H) — optional accounts layered on top of
// Phase C's anonymous identity (lib/identity.ts). Unset env vars = disabled,
// matching the backend's config.py empty-string-disables convention: no
// sign-in UI anywhere, authEnabled stays false, the app behaves exactly
// like Phase C.

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

export const authEnabled = Boolean(SUPABASE_URL && SUPABASE_ANON_KEY);

export const supabase: SupabaseClient | null = authEnabled
  ? createClient(SUPABASE_URL as string, SUPABASE_ANON_KEY as string)
  : null;
