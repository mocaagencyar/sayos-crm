# agent/providers/bridge.py — Proveedor "puente WhatsApp Web" (QR)
#
# Habla con bridge/index.mjs, que corre en el mismo contenedor y escucha solo
# en 127.0.0.1. El puente reenvía a /webhook cada mensaje entrante y cada
# respuesta enviada desde el teléfono, firmados con BRIDGE_SECRET.

import os
import hmac
import logging
import httpx
from fastapi import Request, HTTPException
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorBridge(ProveedorWhatsApp):
    """WhatsApp vinculado como dispositivo (estilo WhatsApp Web) vía el puente local."""

    def __init__(self):
        self.url = os.getenv("BRIDGE_URL", "http://127.0.0.1:3001").rstrip("/")
        self.secret = os.getenv("BRIDGE_SECRET", "")

    def _headers(self) -> dict:
        return {"x-bridge-secret": self.secret}

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        recibido = request.headers.get("x-bridge-secret", "")
        if not self.secret or not hmac.compare_digest(recibido, self.secret):
            raise HTTPException(status_code=401, detail="No autorizado")
        body = await request.json()
        mensajes = []
        for m in body.get("messages", []):
            texto = str(m.get("texto", "")).strip()
            telefono = str(m.get("telefono", "")).strip()
            if not texto or not telefono:
                continue
            mensajes.append(MensajeEntrante(
                telefono=telefono,
                texto=texto,
                mensaje_id=str(m.get("id", "")),
                es_propio=bool(m.get("from_me", False)),
                origen=str(m.get("origen", "user")),
                nombre_contacto=str(m.get("nombre", "") or ""),
            ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(f"{self.url}/send", json={"telefono": telefono, "texto": mensaje}, headers=self._headers())
            if r.status_code != 200:
                logger.error(f"Puente WhatsApp: no se pudo enviar ({r.status_code}) {r.text[:200]}")
                return False
            return True
        except Exception as e:
            logger.error(f"Puente WhatsApp no disponible: {e}")
            return False

    async def estado(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                r = await client.get(f"{self.url}/status", headers=self._headers())
            return r.json()
        except Exception as e:
            return {"estado": "apagado", "qr": "", "numero": "", "error": f"El puente no responde: {e}"}

    async def desvincular(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(f"{self.url}/logout", headers=self._headers())
            return r.status_code == 200
        except Exception:
            return False
