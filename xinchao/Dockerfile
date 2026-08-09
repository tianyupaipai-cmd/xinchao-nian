FROM node:20-alpine

WORKDIR /app
COPY package.json ./
COPY src ./src
COPY configs ./configs
RUN mkdir -p /app/state && chown -R node:node /app

USER node
ENV NODE_ENV=production
EXPOSE 18110
CMD ["node", "src/server.js"]
