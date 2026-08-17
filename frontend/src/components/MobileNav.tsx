"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { MessageSquare, ScrollText, Wand2, Flame } from "lucide-react";
import { navigateWithTransition } from "@/lib/viewTransition";

interface Props {
  active: "chat" | "lore" | "arc" | "make";
}

const TABS = [
  { key: "chat", href: "/chat", label: "Chat", Icon: MessageSquare },
  { key: "lore", href: "/lore", label: "Lore", Icon: ScrollText },
  { key: "make", href: "/make", label: "Make", Icon: Wand2 },
  { key: "arc", href: "/arc", label: "Arc", Icon: Flame },
] as const;

/**
 * Thumb-reach bottom tab bar, mobile only — ModeTabs' pill row is
 * desktop-only above sm. Rendered as the last shrink-0 child in each
 * surface page's flex-col, not fixed-positioned, so it takes up real
 * layout space instead of overlaying a composer or scrollable content
 * that would then need bottom-padding to compensate.
 */
export function MobileNav({ active }: Props) {
  const router = useRouter();

  return (
    <nav
      className="sm:hidden shrink-0 flex items-stretch border-t border-border
                 bg-background/95 backdrop-blur-sm pb-[env(safe-area-inset-bottom)]"
    >
      {TABS.map(({ key, href, label, Icon }) => {
        const isActive = active === key;
        return (
          <Link
            key={key}
            href={href}
            onClick={(e) => navigateWithTransition(router, e, href)}
            className={`flex-1 flex flex-col items-center justify-center gap-1 py-2.5 text-[11px]
                       font-medium transition-colors ${
                         isActive ? "text-accent" : "text-gray-500"
                       }`}
          >
            <Icon size={20} strokeWidth={isActive ? 2.5 : 2} />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
