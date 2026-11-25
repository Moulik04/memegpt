export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * Shared by Masthead's top tabs and MobileNav's bottom tab bar: wraps a
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
  // router.push returns before the new route is drawn, so the update
  // callback waits for the address to change (the App Router updates it
  // when it commits the new page). Rendering is paused inside a view
  // transition, so this polls with timers rather than animation frames.
  const target = new URL(href, window.location.href).pathname;
  document.startViewTransition(
    () =>
      new Promise<void>((resolve) => {
        const started = performance.now();
        router.push(href);
        const wait = () => {
          if (window.location.pathname === target || performance.now() - started > 1500) {
            setTimeout(resolve, 0);
          } else {
            setTimeout(wait, 16);
          }
        };
        wait();
      })
  );
}
