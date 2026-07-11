FROM node:22-alpine AS builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.14.0 --activate

COPY package.json pnpm-workspace.yaml pnpm-lock.yaml /app/
COPY apps/web/package.json /app/apps/web/package.json

RUN pnpm install --filter web... --frozen-lockfile --prod=false

COPY apps/web /app/apps/web

RUN pnpm --filter web build

FROM nginx:1.27-alpine AS runner

COPY --from=builder /app/apps/web/dist /usr/share/nginx/html
COPY infra/docker/web-nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
