---
name: frontend-tokens
description: The MemeGPT design token system and component sourcing rules. Use when building or editing any UI, adding a component, or reviewing frontend work.
paths: frontend/**
---

Every color, size, and type decision comes from the tokens in
`frontend/src/app/globals.css`. Never hardcode a hex value, a font stack,
or a pixel radius in a component.

## The one rule that shapes everything

The interface is monochrome so the memes are the only color on screen.
Every generated meme is a full-color photograph. Chrome that competes with
it is a bug. If you are reaching for a second accent color, stop.

## Sourcing components

Copy mechanics, never aesthetics. When pulling from 21st.dev, Magic UI,
Aceternity, or any registry:
1. Take the behavior — focus management, keyboard handling, animation
   timing, state machine.
2. Strip every visual property it ships with: colors, radii, shadows,
   gradients, font sizes, easing curves.
3. Re-express it in our tokens before it lands in a commit.

A component that still carries its source library's look does not ship.
Registry defaults are what make a site look like every other site built
from that registry.

## Non-negotiables

- No gradients, no glow, no neon. The old purple/pink/cyan direction is
  retired. Do not reintroduce it.
- `prefers-reduced-motion: reduce` disables every non-essential animation.
- Every interactive element is keyboard reachable with a visible focus ring.
- Type scale and spacing come from the token file only.
