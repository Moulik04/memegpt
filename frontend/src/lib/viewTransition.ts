export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Shared by ModeTabs' pill nav and MobileNav's bottom tab bar — wraps a
 * same-origin navigation in document.startViewTransition() when the
 * browser supports it and prefers-reduced-motion isn't set. Modified
 * clicks (cmd/ctrl/shift/middle-click) are left alone so "open in new
 * tab" etc. still work.
 */
export function navigateWithTransition(
  router: { push: (href: string) => void },
  e: React.MouseEvent<HTMLAnchorElement>,
  href: string
) {
  if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  if (!document.startViewTransition || prefersReducedMotion()) {
    router.push(href);
    return;
  }
  document.startViewTransition(() => {
    router.push(href);
  });
}
