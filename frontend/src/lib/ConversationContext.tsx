"use client";

import { createContext, useCallback, useContext, useState } from "react";

interface ConversationContextValue {
  // The currently active persisted conversation (Growth Phase H, Stage 3) —
  // undefined for anonymous use or "no chat selected yet", exactly like
  // useMemeStream's conversationRowId param already tolerates.
  conversationRowId: string | undefined;
  setConversationRowId: (id: string | undefined) => void;
  // Bumped after a turn completes so ConversationSidebar re-fetches its list
  // (a new conversation just got auto-titled, or moved to the top of the
  // newest-first order) without ChatWindow/LoreView needing to know the
  // sidebar exists at all.
  refreshToken: number;
  bumpRefresh: () => void;
  /** The History drawer, opened from the masthead. */
  historyOpen: boolean;
  setHistoryOpen: (open: boolean) => void;
}

const ConversationContext = createContext<ConversationContextValue>({
  conversationRowId: undefined,
  setConversationRowId: () => {},
  refreshToken: 0,
  bumpRefresh: () => {},
  historyOpen: false,
  setHistoryOpen: () => {},
});

/**
 * Shared between HistoryDrawer (lists/selects/deletes conversations), the
 * masthead's History button,
 * and ChatWindow/LoreView (submit against + hydrate from the selected one) —
 * siblings under app/(app)/layout.tsx with no other shared parent state.
 * A no-op default context (rendered when there's no provider, e.g. /arc)
 * means every consumer works without a "is this even wrapped" check.
 */
export function ConversationProvider({ children }: { children: React.ReactNode }) {
  const [conversationRowId, setConversationRowId] = useState<string | undefined>(undefined);
  const [refreshToken, setRefreshToken] = useState(0);
  const bumpRefresh = useCallback(() => setRefreshToken((t) => t + 1), []);
  const [historyOpen, setHistoryOpen] = useState(false);

  return (
    <ConversationContext.Provider
      value={{ conversationRowId, setConversationRowId, refreshToken, bumpRefresh, historyOpen, setHistoryOpen }}
    >
      {children}
    </ConversationContext.Provider>
  );
}

export function useConversation() {
  return useContext(ConversationContext);
}
