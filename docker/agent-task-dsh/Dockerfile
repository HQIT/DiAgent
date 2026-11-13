FROM node:24-bookworm-slim AS build

WORKDIR /app
COPY package.json package-lock.json tsconfig.json ./
RUN npm ci --ignore-scripts
COPY src ./src
RUN npm run build && npm prune --omit=dev --ignore-scripts

FROM node:24-bookworm-slim AS runtime

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends bubblewrap ca-certificates curl git python-is-python3 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./
COPY --from=build /app/dist ./dist

FROM runtime AS service

EXPOSE 8000
ENTRYPOINT ["node", "dist/service/server.js"]

# 默认构建仍生成一次性任务镜像，沿用既有构建入口。
FROM runtime AS task

ENTRYPOINT ["node", "dist/task/main.js"]
