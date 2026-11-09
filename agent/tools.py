# agent/tools.py — Herramientas del agente Max
# Generado por AgentKit

"""
Herramientas específicas del negocio.
Casos de uso: calificación de leads y agendamiento de auditorías gratuitas.
"""

import os
import yaml
import logging
from datetime import datetime

logger = logging.getLogger("agentkit")


def cargar_info_negocio() -> dict:
    """Carga la información del negocio desde business.yaml."""
    try:
        with open("config/business.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        logger.error("config/business.yaml no encontrado")
        return {}


def obtener_horario() -> dict:
    """Retorna el horario de atención del negocio."""
    info = cargar_info_negocio()
    horario_str = info.get("negocio", {}).get("horario", "Lunes a Viernes 9am a 6pm, Sábados 10am a 2pm")

    # Verificar si estamos dentro del horario comercial
    ahora = datetime.now()
    dia_semana = ahora.weekday()    # 0=Lunes, 6=Domingo
    hora_actual = ahora.hour

    esta_abierto = False
    if dia_semana <= 4:  # Lunes a Viernes
        esta_abierto = 9 <= hora_actual < 18
    elif dia_semana == 5:  # Sábado
        esta_abierto = 10 <= hora_actual < 14

    return {
        "horario": horario_str,
        "esta_abierto": esta_abierto,
        "dia_semana": dia_semana,
    }


def evaluar_calificacion_lead(respuestas: dict) -> dict:
    """
    Evalúa si un prospecto califica como cliente ideal para el negocio.

    Args:
        respuestas: Dict con las respuestas del prospecto a las preguntas de calificación
            - tipo_negocio: str (ej: "inmobiliaria", "clínica", "agencia")
            - invierte_en_ads: bool
            - presupuesto_mensual: str (ej: "USD 500/mes", "no invierte")
            - problema_principal: str
            - tiene_equipo_comercial: bool
            - plazo_decision: str (ej: "este mes", "en 3 meses", "solo explorando")

    Returns:
        Dict con:
            - califica: bool
            - score: int (0-100)
            - motivo: str
            - siguiente_paso: str
    """
    score = 0
    motivos = []

    tipo_negocio = respuestas.get("tipo_negocio", "").lower()
    perfiles_ideales = ["inmobiliaria", "inmueble", "propiedad", "desarrolladora", "real estate",
                        "clínica", "clinica", "médico", "medico", "dental", "estética", "estetica",
                        "abogado", "contador", "arquitecto", "coach", "consultora",
                        "concesionaria", "auto", "gimnasio", "capacitación", "construcción"]

    if any(perfil in tipo_negocio for perfil in perfiles_ideales):
        score += 30
        motivos.append("Perfil de negocio ideal")

    if respuestas.get("invierte_en_ads", False):
        score += 25
        motivos.append("Ya invierte en publicidad digital")

    if respuestas.get("tiene_equipo_comercial", False):
        score += 20
        motivos.append("Tiene equipo para atender leads")

    plazo = respuestas.get("plazo_decision", "").lower()
    if any(p in plazo for p in ["mes", "semana", "ahora", "urgente", "pronto"]):
        score += 25
        motivos.append("Plazo de decisión corto")
    elif any(p in plazo for p in ["3 meses", "trimestre"]):
        score += 10

    # Determinar calificación
    if score >= 60:
        return {
            "califica": True,
            "score": score,
            "motivo": " | ".join(motivos),
            "siguiente_paso": "Proponer auditoría gratuita de 30 minutos"
        }
    elif score >= 35:
        return {
            "califica": True,
            "score": score,
            "motivo": "Lead tibio — " + " | ".join(motivos),
            "siguiente_paso": "Nutrir con más información y proponer auditoría"
        }
    else:
        return {
            "califica": False,
            "score": score,
            "motivo": "No cumple criterios mínimos",
            "siguiente_paso": "Cerrar cordialmente y ofrecer recursos gratuitos"
        }


def obtener_info_paquetes() -> str:
    """Retorna un resumen formateado de los paquetes disponibles."""
    info = cargar_info_negocio()
    paquetes = info.get("servicios", {})

    resumen = []
    for key, paquete in paquetes.items():
        nombre = paquete.get("nombre", "")
        setup = paquete.get("precio_setup", "")
        mensual = paquete.get("precio_mensual", "")
        tag = paquete.get("tag", "")
        tag_str = f" ⭐ {tag}" if tag else ""
        resumen.append(f"*{nombre}{tag_str}*: {setup} + {mensual}")

    return "\n".join(resumen) if resumen else "Consultá en mcgrowthagency.com"


def obtener_slots_auditoria() -> list[str]:
    """
    Retorna horarios disponibles para agendar la auditoría gratuita.
    En producción esto se conectaría con Google Calendar o Calendly.
    Por ahora retorna slots fijos de ejemplo.
    """
    # TODO: Integrar con Google Calendar o Calendly para disponibilidad real
    return [
        "Lunes a Viernes de 9am a 6pm",
        "Sábados de 10am a 2pm",
        "Podemos coordinar el horario que mejor te quede."
    ]


def buscar_en_knowledge(consulta: str) -> str:
    """
    Busca información relevante en los archivos de /knowledge.
    Retorna el contenido más relevante encontrado.
    """
    resultados = []
    knowledge_dir = "knowledge"

    if not os.path.exists(knowledge_dir):
        return "No hay archivos de conocimiento disponibles."

    for archivo in os.listdir(knowledge_dir):
        ruta = os.path.join(knowledge_dir, archivo)
        if archivo.startswith(".") or not os.path.isfile(ruta):
            continue
        # Solo archivos de texto — los PDF ya están incorporados en el system prompt
        if not archivo.endswith((".txt", ".md", ".csv", ".json")):
            continue
        try:
            with open(ruta, "r", encoding="utf-8") as f:
                contenido = f.read()
                if consulta.lower() in contenido.lower():
                    resultados.append(f"[{archivo}]: {contenido[:500]}")
        except (UnicodeDecodeError, IOError):
            continue

    if resultados:
        return "\n---\n".join(resultados)
    return "No encontré información adicional específica sobre eso."
