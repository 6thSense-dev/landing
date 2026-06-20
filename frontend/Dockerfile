# syntax=docker/dockerfile:1.6

# ---- Build stage: compile the Vite app into static assets ----
FROM node:22-alpine AS builder
ARG VITE_API_URL
ENV VITE_API_URL=${VITE_API_URL}
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- Runtime stage: serve dist/ with Caddy ----
# Caddy gives on-the-fly compression, fine-grained caching headers, security
# headers and SPA fallback — none of which `vite preview` provides. The runner
# carries no Node/dev toolchain, so the image is small and runs as non-root.
FROM caddy:2-alpine AS runner
RUN addgroup -g 1001 web \
    && adduser -D -u 1001 -G web web \
    && mkdir -p /data /config \
    && chown -R web:web /data /config /srv
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=builder /app/dist /srv
USER web
EXPOSE 3000
CMD ["caddy", "run", "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile"]
