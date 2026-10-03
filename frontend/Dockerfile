FROM node:20-alpine AS builder
WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# NEXT_PUBLIC_* vars are baked in at build time — not available at runtime
ARG NEXT_PUBLIC_API_BASE=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE

# next.config.js evaluates its /api/* rewrite once, during `next build`, so
# BACKEND_URL must exist here too — a runtime-only value leaves the rewrite
# pointing at localhost, which inside this container is nothing.
ARG BACKEND_URL=http://localhost:8000
ENV BACKEND_URL=$BACKEND_URL

# Supabase's URL and anon key are public by design (they ship to every
# browser). Empty means sign-in is hidden, same as an unset local env.
ARG NEXT_PUBLIC_SUPABASE_URL=
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY=
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY

RUN npm run build

# ── Runtime image ────────────────────────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production

# Copy only what next start needs. public/ holds the landing page's hero and
# floating-meme images, the PWA icons and the manifest.
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/next.config.js ./next.config.js

EXPOSE 3000

CMD ["npm", "start"]
