// The landing composer's first message, carried into Chat. Held in memory
// rather than browser storage because photos are File objects; a full
// reload in between drops it and Chat simply opens empty.

export interface LandingHandoff {
  text: string;
  files: File[];
}

let pending: LandingHandoff | null = null;

export function handToChat(handoff: LandingHandoff): void {
  pending = handoff;
}

/** Returns the waiting message once, then forgets it. */
export function takeLandingHandoff(): LandingHandoff | null {
  const taken = pending;
  pending = null;
  return taken;
}
