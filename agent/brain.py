# agent/brain.py — Cerebro del agente Max: conexión con Claude API
# Generado por AgentKit

"""
Lógica de IA del agente Max. Lee el system prompt de prompts.yaml
y genera respuestas usando la API de Anthropic Claude.
"""

import os
import json
import yaml
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente de Anthropic (usa la ANTHROPIC_API_KEY del .env)
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
MODEL_PRINCIPAL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")


async def verificar_ia() -> tuple[bool, str]:
    """Comprueba que la clave y el modelo configurado puedan responder."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False, "ANTHROPIC_API_KEY no configurada"
    try:
        await client.messages.create(
            model=MODEL_PRINCIPAL,
            max_tokens=1,
            system="Respondé únicamente OK.",
            messages=[{"role": "user", "content": "Ping de monitoreo"}],
        )
        return True, "ok"
    except Exception as e:
        logger.error(f"Healthcheck Claude falló: {e}")
        return False, str(e)


def cargar_config_prompts() -> dict:
    """Lee toda la configuración desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    """Lee el system prompt de Max desde config/prompts.yaml."""
    config = cargar_config_prompts()
    return config.get(
        "system_prompt",
        "Sos Max, el asistente virtual de tu negocio. Respondé siempre en español."
    )


def obtener_mensaje_error() -> str:
    """Retorna el mensaje de error configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get(
        "error_message",
        "Lo siento, estoy teniendo un problema técnico en este momento. En unos minutos te escribo yo para asegurarme de que te atendemos bien."
    )


def obtener_mensaje_fallback() -> str:
    """Retorna el mensaje de fallback configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get(
        "fallback_message",
        "Disculpá, no entendí bien tu mensaje. ¿Podés contarme un poco más sobre lo que necesitás?"
    )


async def generar_respuesta(mensaje: str, historial: list[dict]) -> str:
    """
    Genera una respuesta usando Claude API.

    Args:
        mensaje: El mensaje nuevo del prospecto
        historial: Lista de mensajes anteriores [{"role": "user/assistant", "content": "..."}]

    Returns:
        La respuesta generada por Max (Claude)
    """
    # Si el mensaje es muy corto o vacío, usar fallback
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    system_prompt = cargar_system_prompt()

    # Construir mensajes para la API: historial + mensaje actual
    mensajes = []
    for msg in historial:
        mensajes.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # Agregar el mensaje actual del prospecto
    mensajes.append({
        "role": "user",
        "content": mensaje
    })

    try:
        response = await client.messages.create(
            model=MODEL_PRINCIPAL,
            max_tokens=1024,
            system=system_prompt,
            messages=mensajes
        )

        respuesta = response.content[0].text
        logger.info(
            f"Respuesta generada — "
            f"tokens: {response.usage.input_tokens} in / {response.usage.output_tokens} out"
        )
        return respuesta

    except Exception as e:
        logger.error(f"Error Claude API: {e}")
        return obtener_mensaje_error()


async def extraer_info_lead(historial: list[dict]) -> dict:
    """
    Usa Claude Haiku para extraer datos clave del lead de la conversación.
    Rápido y barato — solo se llama una vez al calificar.
    """
    conversacion = "\n".join(
        f"{'PROSPECTO' if m['role'] == 'user' else 'MAX'}: {m['content']}"
        for m in historial
    )

    fallback = {"nombre": "No indicó", "rubro": "No indicó", "presupuesto": "No indicó", "interes": "No indicó", "sentiment_score": 50, "sentiment_label": "neutral", "resumen": "No disponible"}

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system="Sos un extractor de datos. Respondés SOLO con JSON válido, sin explicaciones ni markdown.",
            messages=[{
                "role": "user",
                "content": (
                    "De esta conversación de WhatsApp de una agencia de marketing, extraé:\n"
                    "- nombre: nombre del prospecto (si lo mencionó, sino 'No indicó')\n"
                    "- rubro: industria o tipo de negocio\n"
                    "- presupuesto: cuánto invierte o está dispuesto a invertir en publicidad\n"
                    "- interes: qué le interesa específicamente de los servicios\n\n"
                    "- sentiment_score: puntaje de sentimiento del prospecto entre 0 (muy negativo) y 100 (muy positivo)\n"
                    "- sentiment_label: una sola palabra: negativo, neutral o positivo\n"
                    "- resumen: resumen comercial de máximo 160 caracteres\n\n"
                    f"Conversación:\n{conversacion}\n\n"
                    'Respondé SOLO con este JSON (sin markdown):\n'
                    '{"nombre": "...", "rubro": "...", "presupuesto": "...", "interes": "...", "sentiment_score": 0, "sentiment_label": "...", "resumen": "..."}'
                )
            }]
        )
        texto = response.content[0].text.strip()
        # Limpiar si viene con markdown
        if texto.startswith("```"):
            texto = texto.split("```")[1].lstrip("json").strip()
        return json.loads(texto)
    except Exception as e:
        logger.error(f"Error extrayendo info del lead: {e}")
        return fallback
