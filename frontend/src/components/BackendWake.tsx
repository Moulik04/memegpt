"use client";

import { useEffect } from "react";
import { wakeBackend } from "@/lib/api";

// Rendered by the landing page and the four app surfaces. Not by the
// coming-soon page, /privacy or the share page, which never need the
// backend to be quick.
export function BackendWake() {
  useEffect(() => {
    wakeBackend();
  }, []);
  return null;
}
