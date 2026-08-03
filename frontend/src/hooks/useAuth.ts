"use client";

import { useContext } from "react";
import { AuthContext } from "@/lib/AuthProvider";

export function useAuth() {
  return useContext(AuthContext);
}
