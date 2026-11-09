# agent/telegram.py — Notificaciones Telegram del negocio
# Envía alertas al equipo cuando Max califica un lead

import os
import logging
import httpx
from dotenv import load_dotenv
from agent.tools import cargar_info_negocio

load_dotenv()
logger = logging.getLogger("agentkit")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def _nombre_negocio() -> str:
    """Nombre del negocio desde config/business.yaml, para no hardcodear un cliente en el código base."""
    return cargar_info_negocio().get("negocio", {}).get("nombre", "tu negocio")


async def notificar_lead_calificado(telefono: str, info: dict) -> bool:
    """
    Envía una notificación a Telegram cuando Max califica un lead.

    Args:
        telefono: Número del prospecto
        info: Dict con nombre, rubro, presupuesto, interes extraídos por Claude

    Returns:
        True si la notificación fue enviada exitosamente
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados — notificación omitida")
        return False


    telefono_limpio = telefono.replace("@s.whatsapp.net", "").replace("@c.us", "")

    nombre = info.get("nombre", "No indicó")
    rubro = info.get("rubro", "No indicó")
    presupuesto = info.get("presupuesto", "No indicó")
    interes = info.get("interes", "No indicó")
    sentiment_score = info.get("sentiment_score", 50)
    sentiment_label = info.get("sentiment_label", "neutral")

    mensaje = (
        f"🔥 *LEAD CALIFICADO — {_nombre_negocio()}*\n\n"
        f"📱 *WhatsApp:* +{telefono_limpio}\n"
        f"👤 *Nombre:* {nombre}\n"
        f"🏢 *Rubro:* {rubro}\n"
        f"💰 *Presupuesto en ads:* {presupuesto}\n"
        f"🎯 *Interés:* {interes}\n"
        f"🧠 *Sentimiento:* {sentiment_score}/100 ({sentiment_label})\n"
        f"🕐 *Hora:* {_hora_actual()}\n\n"
        "👆 _Hacer seguimiento desde el numero principal_"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensaje,
        "parse_mode": "Markdown",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            if r.status_code == 200:
                logger.info(f"Notificacion Telegram enviada para lead {telefono_limpio}")
                return True
            else:
                logger.error(f"Error Telegram: {r.status_code} — {r.text}")
                return False
    except Exception as e:
        logger.error(f"Error enviando notificacion Telegram: {e}")
        return False


async def notificar_lead_revision(telefono: str, info: dict, motivo: str = "Caso fuera del perfil habitual o con calificación dudosa") -> bool:
    """Avisa al equipo sin descartar el contacto cuando Max no tiene certeza."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram no configurado — alerta de revisión omitida")
        return False
    telefono_limpio = telefono.replace("@s.whatsapp.net", "").replace("@c.us", "")
    mensaje = (
        f"⚠️ *REVISAR LEAD — {_nombre_negocio()}*\n\n"
        f"📱 *WhatsApp:* +{telefono_limpio}\n"
        f"👤 *Nombre:* {info.get('nombre', 'No indicó')}\n"
        f"🏢 *Rubro:* {info.get('rubro', 'No indicó')}\n"
        f"💰 *Presupuesto:* {info.get('presupuesto', 'No indicó')}\n"
        f"🎯 *Interés:* {info.get('interes', 'No indicó')}\n"
        f"📝 *Motivo:* {motivo}\n\n"
        "Max lo dejó en seguimiento. Decidí manualmente si avanzar."
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"})
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Error enviando alerta de revisión: {e}")
        return False


async def notificar_nuevo_mensaje(telefono: str, mensaje: str, nombre: str = "", es_primer_mensaje: bool = False) -> bool:
    """
    Avisa a Telegram cada vez que alguien le escribe a Max, calificado o no.
    Pensado como notificación rápida mientras no hay otro canal de atención en vivo.

    Args:
        telefono: Número del contacto
        mensaje: Texto que mandó
        nombre: Nombre del contacto si ya se conoce (perfil de Meta o dato guardado)
        es_primer_mensaje: True si es la primera vez que este número escribe
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_ID no configurados — notificación omitida")
        return False

    telefono_limpio = telefono.replace("@s.whatsapp.net", "").replace("@c.us", "")
    texto_corto = mensaje if len(mensaje) <= 300 else mensaje[:300] + "…"
    negocio = _nombre_negocio()
    encabezado = f"💬 *NUEVO CONTACTO — {negocio}*" if es_primer_mensaje else f"💬 *Nuevo mensaje — {negocio}*"
    linea_nombre = f"👤 *Nombre:* {nombre}\n" if nombre else ""

    mensaje_telegram = (
        f"{encabezado}\n\n"
        f"📱 *WhatsApp:* +{telefono_limpio}\n"
        f"{linea_nombre}"
        f"🗨️ *Dice:* {texto_corto}\n"
        f"🕐 *Hora:* {_hora_actual()}"
    )

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensaje_telegram, "parse_mode": "Markdown"})
            if r.status_code != 200:
                logger.error(f"Error Telegram (nuevo mensaje): {r.status_code} — {r.text}")
            return r.status_code == 200
    except Exception as e:
        logger.error(f"Error enviando notificacion Telegram (nuevo mensaje): {e}")
        return False


def _hora_actual() -> str:
    """Retorna la hora actual formateada."""
    from datetime import datetime
    return datetime.now().strftime("%d/%m/%Y %H:%M")
