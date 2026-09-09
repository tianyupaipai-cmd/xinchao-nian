# 基础镜像可用 --build-arg NODE_IMAGE=... 换（例如仓库拉不到时用本机已有的 node:22-alpine）
ARG NODE_IMAGE=node:20-alpine
FROM ${NODE_IMAGE}

WORKDIR /app
COPY package.json ./
COPY src ./src
COPY configs ./configs
RUN mkdir -p /app/state && chown -R node:node /app

USER node
ENV NODE_ENV=production
EXPOSE 18110
CMD ["node", "src/server.js"]
