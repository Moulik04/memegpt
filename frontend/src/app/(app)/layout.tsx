import { BackendWake } from "@/components/BackendWake";
import { ConversationProvider } from "@/lib/ConversationContext";
import { HistoryDrawer } from "@/components/HistoryDrawer";

/**
 * Wraps /chat and /lore only, the two surfaces with saved conversations.
 * Signed in, the History drawer opens over the page from the masthead's
 * History button. It sits outside the page's own layout, so it never
 * narrows it; signed out it renders nothing.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ConversationProvider>
      <BackendWake />
      <div className="flex flex-col h-dvh">{children}</div>
      <HistoryDrawer />
    </ConversationProvider>
  );
}
