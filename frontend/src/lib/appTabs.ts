export type AppTab = "chat" | "lore" | "make" | "arc";

/** The four app surfaces, in navigation order. Shared by the desktop top
 * tabs (Masthead) and the phone bottom bar (MobileNav). */
export const APP_TABS: ReadonlyArray<{ key: AppTab; href: string; label: string }> = [
  { key: "chat", href: "/chat", label: "Chat" },
  { key: "lore", href: "/lore", label: "Lore" },
  { key: "make", href: "/make", label: "Make" },
  { key: "arc", href: "/arc", label: "Arc" },
];
