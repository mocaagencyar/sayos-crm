#!/bin/sh
# run.sh — Arranque del contenedor: CRM (FastAPI) + puente de WhatsApp (si corresponde)
set -e

# Secreto compartido entre el CRM y el puente. Si no viene de Render, se genera
# uno al azar en cada arranque (solo lo usan estos dos procesos, en 127.0.0.1).
if [ -z "$BRIDGE_SECRET" ]; then
  BRIDGE_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(24))')"
fi
export BRIDGE_SECRET

if [ "$WHATSAPP_PROVIDER" = "bridge" ]; then
  # El puente se reinicia solo si se cae
  (
    while true; do
      node /app/bridge/index.mjs || true
      echo "[run] El puente de WhatsApp se detuvo; reinicio en 5 s"
      sleep 5
    done
  ) &
fi

exec uvicorn agent.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*'
