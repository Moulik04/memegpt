"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import { AnimatePresence, motion } from "motion/react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks/useAuth";
import { useConversation } from "@/lib/ConversationContext";
import {
  createConversation,
  deleteConversation,
  listConversations,
  memeImageUrl,
  type Surface,
} from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
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
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

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

  function requestDelete(id: string, e: React.MouseEvent) {
    e.stopPropagation();
    setDeleteTarget(id);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    await deleteConversation(deleteTarget).catch(() => {});
    if (conversationRowId === deleteTarget) setConversationRowId(undefined);
    setDeleting(false);
    setDeleteTarget(null);
    refresh();
  }

  return (
    <aside className="w-56 shrink-0 border-r border-border bg-background/60 flex flex-col h-full">
      <div className="p-3">
        <button
          type="button"
          onClick={handleNewChat}
          className="w-full text-xs font-medium rounded-xl px-3 py-2 bg-card border border-border
                     text-gray-300 hover:border-accent/60 hover:text-white hover:shadow-lg
                     hover:-translate-y-0.5 transition-all duration-200"
        >
          + New chat
        </button>
      </div>
      <nav className="flex-1 overflow-y-auto chat-scroll px-2 pb-3 flex flex-col gap-1">
        <AnimatePresence mode="popLayout" initial={false}>
          {conversations.map((c, i) => (
            <motion.div
              key={c.id}
              layout
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96 }}
              transition={{ duration: 0.2, delay: Math.min(i, 8) * 0.03 }}
              role="button"
              tabIndex={0}
              onClick={() => setConversationRowId(c.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter") setConversationRowId(c.id);
              }}
              className={`group flex items-center justify-between gap-2 text-xs rounded-lg px-3 py-2
                          cursor-pointer transition-colors ${
                            c.id === conversationRowId
                              ? "bg-accent/15 text-white border border-accent/40"
                              : "text-gray-400 hover:bg-white/5 border border-transparent"
                          }`}
            >
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <div className="w-7 h-7 rounded-md overflow-hidden shrink-0 bg-ink-2">
                  {c.thumbnail_url && (
                    <Image
                      src={memeImageUrl(c.thumbnail_url)}
                      alt=""
                      width={28}
                      height={28}
                      unoptimized
                      className="w-full h-full object-cover"
                    />
                  )}
                </div>
                <span className="truncate">{c.title ?? "New chat"}</span>
              </div>
              <button
                type="button"
                onClick={(e) => requestDelete(c.id, e)}
                title="Delete"
                aria-label="Delete this chat"
                className="opacity-0 group-hover:opacity-100 text-gray-600 hover:text-red-400
                           transition-opacity shrink-0"
              >
                ✕
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
        {loaded && conversations.length === 0 && (
          <p className="text-[11px] text-gray-600 px-3 py-2">No chats yet.</p>
        )}
      </nav>

      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete this chat?</DialogTitle>
            <DialogDescription>
              This also un-teaches what MemeGPT learned from it: the memes
              it generated, any feedback on them, and any lore terms it
              picked up get removed too — not just hidden from this list.
              This can&apos;t be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={deleting}>
              {deleting ? "Deleting…" : "Delete chat"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </aside>
  );
}
