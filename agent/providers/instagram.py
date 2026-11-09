"""Adaptador mínimo para Instagram Messaging API de Meta."""
import os
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante


class ProveedorInstagram(ProveedorWhatsApp):
    def __init__(self, access_token=None, verify_token=None):
        self.access_token = access_token or os.getenv("INSTAGRAM_ACCESS_TOKEN")
        self.verify_token = verify_token or os.getenv("INSTAGRAM_VERIFY_TOKEN", "mcgrowth-instagram-2026")
        self.api_version = os.getenv("META_API_VERSION", "v21.0")
        self.login_mode = os.getenv("INSTAGRAM_LOGIN_MODE", "instagram").lower()
        self.ig_user_id = os.getenv("INSTAGRAM_IG_USER_ID")

    async def validar_webhook(self, request: Request):
        params = request.query_params
        if params.get("hub.mode") == "subscribe" and params.get("hub.verify_token") == self.verify_token:
            return int(params.get("hub.challenge", "0"))
        return None

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        body = await request.json()
        mensajes = []
        for entry in body.get("entry", []):
            for item in entry.get("messaging", []):
                texto = item.get("message", {}).get("text", "")
                sender = item.get("sender", {}).get("id", "")
                if texto and sender:
                    mensajes.append(MensajeEntrante(
                        telefono="ig:" + sender,
                        texto=texto,
                        mensaje_id=item.get("message", {}).get("mid", ""),
                        es_propio=False,
                        canal_id="instagram",
                    ))
        return mensajes

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        if not self.access_token:
            return False
        recipient = telefono.removeprefix("ig:")
        if self.login_mode == "facebook":
            if not self.ig_user_id:
                return False
            url = f"https://graph.facebook.com/{self.api_version}/{self.ig_user_id}/messages"
        else:
            url = f"https://graph.instagram.com/{self.api_version}/me/messages"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, params={"access_token": self.access_token}, json={"recipient": {"id": recipient}, "message": {"text": mensaje}})
                if response.status_code >= 300:
                    import logging
                    logging.getLogger("agentkit").error("Error Instagram API: %s — %s", response.status_code, response.text)
                    return False
                return True
        except Exception:
            return False
