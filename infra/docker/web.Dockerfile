FROM node:22-alpine AS builder

WORKDIR /app

RUN corepack enable

COPY package.json pnpm-workspace.yaml /app/
COPY apps/web/package.json /app/apps/web/package.json

RUN pnpm install --filter web... --no-frozen-lockfile

COPY . /app

RUN pnpm --filter web build

FROM node:22-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production

RUN corepack enable

COPY --from=builder /app/apps/web/.next/standalone /app
COPY --from=builder /app/apps/web/.next/static /app/apps/web/.next/static
COPY --from=builder /app/apps/web/public /app/apps/web/public
COPY infra/docker/web-entrypoint.sh /app/infra/docker/web-entrypoint.sh

EXPOSE 3000

ENTRYPOINT ["sh", "/app/infra/docker/web-entrypoint.sh"]
