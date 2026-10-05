# Multi-stage build producing a minimal standalone Next.js server (see
# output: "standalone" in next.config.ts) — the runtime image ships only
# the traced dependencies, not the full node_modules tree.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# NEXT_PUBLIC_* vars are inlined into the JS bundle at build time, not read
# at runtime — setting NEXT_PUBLIC_API_URL as a plain Railway environment
# variable on this service does nothing. It must be passed as a build ARG
# (Railway: Settings -> Build -> add it under "Build Variables", not the
# regular runtime "Variables" tab).
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# 0.0.0.0, not the standalone server's default of localhost — otherwise
# nothing outside the container (including Railway's own proxy) can reach
# it. $PORT is Railway's convention for which port to actually listen on.
ENV HOSTNAME="0.0.0.0"
ENV PORT=3000
EXPOSE 3000

CMD ["node", "server.js"]
