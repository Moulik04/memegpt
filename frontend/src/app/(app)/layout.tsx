import { ConversationProvider } from "@/lib/ConversationContext";
import { ConversationSidebar } from "@/components/ConversationSidebar";

/**
 * Growth Phase H, Stage 3 — wraps /chat and /lore ONLY (not /arc, /m/[id],
 * /share, /maintenance), adding the conversation sidebar in a flex-row.
 * ConversationSidebar renders null when signed out, so anonymous visitors
 * see byte-identical pages to before this layout existed.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ConversationProvider>
      <div className="flex h-dvh">
        <ConversationSidebar />
        <div className="flex-1 min-w-0 flex flex-col">{children}</div>
      </div>
    </ConversationProvider>
  );
}
