FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium ca-certificates fonts-liberation && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN npm install --omit=dev playwright-core@1.56.1
COPY worker.js /app/worker.js
USER node
CMD ["node", "/app/worker.js"]
