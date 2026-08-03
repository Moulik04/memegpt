"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useConversation } from "@/lib/ConversationContext";
import { createConversation, deleteConversation, listConversations, type Surface } from "@/lib/api";
import type { ConversationSummary } from "@/types";

function surfaceFromPath(pathname: string | null): Surface {
  return pathname?.startsWith("/lore") ? "lore" : "chat";
}

/**
 * Renders null when signed out — anonymous use is completely unaffected,
 * matching AuthControl.tsx's precedent. Lives in app/(app)/layout.tsx,
 * shared by both /chat and /lore, but only ever lists+creates conversations
 * for whichever surface the current route is (surfaceFromPath), since each
 * conversation row is tagged with exactly one surface.
 */
export function ConversationSidebar() {
  const { user } = useAuth();
  const pathname = usePathname();
  const surface = surfaceFromPath(pathname);
  const { conversationRowId, setConversationRowId, refreshToken } = useConversation();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(async () => {
    if (!user) return;
    const rows = await listConversations(surface).catch(() => []);
    setConversations(rows);
    setLoaded(true);
  }, [user, surface]);

  useEffect(() => {
    refresh();
  }, [refresh, refreshToken]);

  // Switching between /chat and /lore clears the active selection — each
  // surface's sidebar only ever lists its own conversations, so a selected
  // id from the other surface would be meaningless here.
  useEffect(() => {
    setConversationRowId(undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surface]);

  if (!user) return null;

  async function handleNewChat() {
    const created = await createConversation(surface).catch(() => null);
    if (!created) return;
    setConversationRowId(created.id);
    refresh();
  }

  async function handleDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    if (!window.confirm("Delete this chat? This can't be undone.")) return;
    await deleteConversation(id).catch(() => {});
    if (conversationRowId === id) setConversationRowId(undefined);
    refresh();
  }

  return (
    <aside className="w-56 shrink-0 border-r border-gray-800/60 bg-gray-950/60 flex flex-col h-full">
      <div className="p-3">
        <button
          type="button"
          onClick={handleNewChat}
          className="w-full text-xs font-medium rounded-xl px-3 py-2 bg-[#13131e] border border-gray-800
                     text-gray-300 hover:border-brand-600/60 hover:text-white transition-colors"
        >
          + New chat
        </button>
      </div>
      <nav className="flex-1 overflow-y-auto chat-scroll px-2 pb-3 flex flex-col gap-1">
        {conversations.map((c) => (
          <div
            key={c.id}
            role="button"
            tabIndex={0}
            onClick={() => setConversationRowId(c.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter") setConversationRowId(c.id);
            }}
            className={`group flex items-center justify-between gap-2 text-xs rounded-lg px-3 py-2
                        cursor-pointer transition-colors ${
                          c.id === conversationRowId
                            ? "bg-brand-600/15 text-white border border-brand-600/40"
                            : "text-gray-400 hover:bg-white/5 border border-transparent"
                        }`}
          >
            <span className="truncate">{c.title ?? "New chat"}</span>
            <button
              type="button"
              onClick={(e) => handleDelete(c.id, e)}
              title="Delete"
              className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400
                         transition-opacity shrink-0"
            >
              ✕
            </button>
          </div>
        ))}
        {loaded && conversations.length === 0 && (
          <p className="text-[11px] text-gray-600 px-3 py-2">No chats yet.</p>
        )}
      </nav>
    </aside>
  );
}
