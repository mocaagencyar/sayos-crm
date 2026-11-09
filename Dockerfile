# ── Etapa 1: dependencias del puente de WhatsApp (Node + Baileys) ──
FROM node:22-bookworm-slim AS bridge
# git: algunas dependencias de Baileys se instalan desde GitHub
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /bridge
COPY bridge/package.json ./
RUN npm install --omit=dev --no-audit --no-fund

# ── Etapa 2: CRM (Python) + binario de Node para el puente ──
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=bridge /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=bridge /bridge/node_modules /app/bridge/node_modules
RUN chmod +x /app/run.sh

EXPOSE 8000
CMD ["/app/run.sh"]
