"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Dialog as DialogPrimitive } from "radix-ui";
import { useAuth } from "@/hooks/useAuth";
import { useConversation } from "@/lib/ConversationContext";
import { deleteConversation, listConversations, memeImageUrl, type Surface } from "@/lib/api";
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

const DELETE_FAILED = "MemeGPT couldn't delete that chat. Please try again.";

function surfaceFromPath(pathname: string | null): Surface {
  return pathname?.startsWith("/lore") ? "lore" : "chat";
}

/**
 * Saved chats, signed in only. A drawer over the page from the left edge,
 * opened by the masthead's History button, on Chat and Lore. Each surface
 * lists only its own conversations. Renders nothing when signed out.
 */
export function HistoryDrawer() {
  const { user } = useAuth();
  const pathname = usePathname();
  const surface = surfaceFromPath(pathname);
  const { conversationRowId, setConversationRowId, refreshToken, historyOpen, setHistoryOpen } =
    useConversation();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<ConversationSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState(false);

  const refresh = useCallback(async () => {
    if (!user) return;
    const rows = await listConversations(surface).catch(() => []);
    setConversations(rows);
    setLoaded(true);
  }, [user, surface]);

  useEffect(() => {
    refresh();
  }, [refresh, refreshToken]);

  // A selection from the other surface means nothing here.
  useEffect(() => {
    setConversationRowId(undefined);
    setHistoryOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [surface]);

  // Signing out closes the drawer.
  useEffect(() => {
    if (!user) setHistoryOpen(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  if (!user) return null;

  function open(id: string | undefined) {
    setConversationRowId(id);
    setHistoryOpen(false);
  }

  async function confirmDelete() {
    if (!deleteTarget) return;
    setDeleting(true);
    setDeleteError(false);
    try {
      await deleteConversation(deleteTarget.id);
    } catch {
      setDeleteError(true);
      setDeleting(false);
      return;
    }
    if (conversationRowId === deleteTarget.id) setConversationRowId(undefined);
    setDeleting(false);
    setDeleteTarget(null);
    refresh();
  }

  return (
    <DialogPrimitive.Root open={historyOpen} onOpenChange={setHistoryOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className="fixed inset-0 z-40 bg-paper/20 data-open:animate-in data-open:fade-in-0
                     data-closed:animate-out data-closed:fade-out-0 duration-[var(--duration-settle)]
                     motion-reduce:animate-none"
        />
        <DialogPrimitive.Content
          className="fixed inset-y-0 left-0 z-40 w-[min(24rem,calc(100vw-3rem))] flex flex-col
                     bg-background border-r border-border shadow-overlay outline-none
                     pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)]
                     data-open:animate-in data-open:slide-in-from-left data-closed:animate-out
                     data-closed:slide-out-to-left duration-[var(--duration-settle)] ease-[var(--ease-settle)]
                     motion-reduce:animate-none"
        >
          <div className="flex items-center justify-between gap-4 px-4 md:px-6 min-h-14 md:min-h-[72px]
                          border-b-2 border-brand">
            <DialogPrimitive.Title className="font-display text-2xl leading-none">History</DialogPrimitive.Title>
            <DialogPrimitive.Close className="min-h-11 px-2 text-base font-medium text-foreground">
              Close
            </DialogPrimitive.Close>
          </div>

          <div className="px-4 md:px-6 pt-4 pb-3 flex flex-col gap-3 border-b border-border">
            <DialogPrimitive.Description className="text-base text-muted-foreground">
              History saved across devices.
            </DialogPrimitive.Description>
            <button
              type="button"
              onClick={() => open(undefined)}
              className="self-start min-h-11 px-4 border border-input text-base font-medium text-foreground
                         hover:bg-muted transition-colors duration-[var(--duration-fast)]"
            >
              New chat
            </button>
          </div>

          <ul className="flex-1 overflow-y-auto py-2">
            {conversations.map((c) => {
              const active = c.id === conversationRowId;
              const title = c.title ?? "New chat";
              return (
                <li
                  key={c.id}
                  className={`flex items-center gap-1 pr-2 border-l-2 ${
                    active ? "bg-muted border-brand" : "border-transparent hover:bg-muted"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => open(c.id)}
                    aria-current={active ? "true" : undefined}
                    className="flex-1 min-w-0 min-h-14 flex items-center gap-3 pl-4 md:pl-6 pr-2 py-2 text-left
                               focus-visible:outline-offset-[-2px]"
                  >
                    <span className="w-10 h-10 shrink-0 bg-meme-mat border border-meme-edge flex items-center justify-center">
                      {c.thumbnail_url && (
                        // eslint-disable-next-line @next/next/no-img-element -- natural ratio, any origin
                        <img
                          src={memeImageUrl(c.thumbnail_url)}
                          alt=""
                          className="max-w-full max-h-full w-auto h-auto"
                        />
                      )}
                    </span>
                    <span className={`truncate text-base ${active ? "text-foreground font-medium" : "text-foreground"}`}>
                      {title}
                    </span>
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDeleteError(false);
                      setDeleteTarget(c);
                    }}
                    aria-label={`Delete ${title}`}
                    className="shrink-0 min-h-11 px-2 text-base text-muted-foreground hover:text-foreground
                               transition-colors duration-[var(--duration-fast)]"
                  >
                    Delete
                  </button>
                </li>
              );
            })}
            {loaded && conversations.length === 0 && (
              <li className="px-4 md:px-6 py-3 text-base text-muted-foreground">No chats yet.</li>
            )}
          </ul>
          {/* Inside the drawer, so radix treats it as part of it, not an outside click. */}
          <Dialog open={deleteTarget !== null} onOpenChange={(o) => !o && !deleting && setDeleteTarget(null)}>
            <DialogContent showCloseButton={false}>
              <DialogHeader>
                <DialogTitle>Delete this chat?</DialogTitle>
                <DialogDescription>
                  This also removes the memes MemeGPT made in it, any ratings on them, and any lore terms it
                  picked up. Share links to those memes stop working. This can&apos;t be undone.
                </DialogDescription>
              </DialogHeader>
              {deleteError && (
                <p role="alert" className="text-sm text-destructive">
                  {DELETE_FAILED}
                </p>
              )}
              <DialogFooter>
                <Button variant="outline" className="min-h-11" onClick={() => setDeleteTarget(null)} disabled={deleting}>
                  Cancel
                </Button>
                <Button variant="destructive" className="min-h-11" onClick={confirmDelete} disabled={deleting}>
                  {deleting ? "Deleting…" : "Delete chat"}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
