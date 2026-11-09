# agent/providers/whapi.py — Adaptador para Whapi.cloud
# Generado por AgentKit

import os
import logging
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorWhapi(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando Whapi.cloud (REST API simple)."""

    def __init__(self):
        self.token = os.getenv("WHAPI_TOKEN")
        self.url_envio = "https://gate.whapi.cloud/messages/text"

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload de Whapi.cloud y normaliza los mensajes."""
        body = await request.json()
        mensajes = []
        for msg in body.get("messages", []):
            # Solo procesamos mensajes de texto
            texto = msg.get("text", {}).get("body", "")
            if not texto:
                continue
            mensajes.append(MensajeEntrante(
                telefono=msg.get("chat_id", ""),
                texto=texto,
                mensaje_id=msg.get("id", ""),
                es_propio=msg.get("from_me", False),
            ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía un mensaje de texto via Whapi.cloud."""
        if not self.token:
            logger.warning("WHAPI_TOKEN no configurado — mensaje no enviado")
            return False

        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        payload = {
            "to": telefono,
            "body": mensaje,
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(
                    self.url_envio,
                    json=payload,
                    headers=headers,
                )
                if r.status_code != 200:
                    logger.error(f"Error Whapi: {r.status_code} — {r.text}")
                    return False
                return True
        except httpx.TimeoutException:
            logger.error("Timeout al enviar mensaje via Whapi")
            return False
        except Exception as e:
            logger.error(f"Error inesperado enviando mensaje: {e}")
            return False
