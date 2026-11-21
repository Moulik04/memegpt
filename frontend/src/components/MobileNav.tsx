"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { navigateWithTransition } from "@/lib/viewTransition";
import { APP_TABS, type AppTab } from "@/lib/appTabs";

interface Props {
  /** Omit on the landing page, where no tab is active. */
  active?: AppTab;
  /**
   * The landing page scrolls the whole document, so its bar is fixed to
   * the bottom and the page reserves its height. App pages scroll inside
   * an h-dvh column, where the bar is the last in-flow child and never
   * covers a field.
   */
  fixed?: boolean;
}

/** Below 768px, the only tab navigation: four equal text tabs, the active
 * one underlined in red. */
export function MobileNav({ active, fixed = false }: Props) {
  const router = useRouter();

  return (
    <nav
      aria-label="MemeGPT"
      data-fixed-tabs={fixed ? "" : undefined}
      className={`md:hidden flex items-stretch border-t border-border bg-background
                  pb-[env(safe-area-inset-bottom)] ${fixed ? "fixed bottom-0 inset-x-0 z-30" : "shrink-0"}`}
    >
      {APP_TABS.map(({ key, href, label }) => {
        const isActive = key === active;
        return (
          <Link
            key={key}
            href={href}
            aria-current={isActive ? "page" : undefined}
            onClick={(e) => navigateWithTransition(router, e, href)}
            className={`flex-1 h-12 flex items-center justify-center text-base font-medium transition-colors
                        duration-[var(--duration-fast)] ${
                          isActive
                            ? "text-foreground underline decoration-brand decoration-[3px] underline-offset-8"
                            : "text-muted-foreground"
                        }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
