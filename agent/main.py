# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit — Agente Max (base reutilizable)

"""
Servidor principal del agente Max.
Funciona con cualquier proveedor (Whapi, Meta, Twilio) gracias a la capa de providers.
"""

import os
import json
import secrets
import hmac
import hashlib
import time
import csv
import io
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, Depends, status, Form
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import PlainTextResponse, HTMLResponse, RedirectResponse, StreamingResponse, FileResponse
from dotenv import load_dotenv

from agent.brain import generar_respuesta, extraer_info_lead, verificar_ia
from agent.memory import DATABASE_URL, inicializar_db, guardar_mensaje, obtener_historial, registrar_lead, registrar_actividad, marcar_leido, marcar_lead_notificado, marcar_calificado, marcar_revision_notificada, actualizar_info_lead, actualizar_nombre_lead, obtener_leads, obtener_conversacion, obtener_conversaciones, obtener_todos_los_mensajes, marcar_lead_cerrado, marcar_lead_descartado, cambiar_estado_lead, actualizar_seguimiento_lead, actualizar_datos_oportunidad, eliminar_lead, obtener_canal, obtener_canales, guardar_canal, alternar_canal, obtener_control_contacto, establecer_control_contacto, obtener_configuracion, guardar_configuracion
from agent.providers import obtener_proveedor
from agent.tools import cargar_info_negocio
from agent.telegram import notificar_lead_calificado, notificar_lead_revision, notificar_nuevo_mensaje

load_dotenv()

# Configuración de logging según entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("agentkit")

# Proveedor de WhatsApp (Whapi.cloud, configurado en .env)
proveedor = obtener_proveedor()
instagram = None
PORT = int(os.getenv("PORT", 8000))
BOT_ENABLED = True
security = HTTPBasic(auto_error=False)
SESSION_COOKIE = "mc_growth_session"

# ── Marca del workspace — configurable por cliente, sin tocar código ──────
# Base blanca: los defaults son genéricos a propósito, NO los de ninguna
# agencia. Cada cliente se identifica completando BRAND_* en su propio .env —
# así el mismo código sirve para la agencia que sea, con la marca que sea.
BRAND_NAME = os.getenv("BRAND_NAME", "CRM")
BRAND_COMPANY = os.getenv("BRAND_COMPANY", "Tu Negocio")
BRAND_TAGLINE = os.getenv("BRAND_TAGLINE", "Asistente de WhatsApp con IA")
BRAND_SHORT = os.getenv("BRAND_SHORT", "AI")
BRAND_COLOR = os.getenv("BRAND_COLOR", "#2563eb")
BRAND_COLOR_2 = os.getenv("BRAND_COLOR_2", "#60a5fa")
BRAND_LOGO_URL = os.getenv("BRAND_LOGO_URL", "")


def _marca(html: str) -> str:
    """
    Reemplaza los textos y colores de marca hardcodeados en el HTML por los
    configurados en las variables BRAND_* — así el mismo dashboard sirve
    para cualquier cliente de cualquier agencia sin tocar este archivo.
    El orden importa: la frase larga va antes que la corta para no dejarla
    pisada a medias (ej. "CRM" antes que una palabra que lo contenga).
    """
    return (
        html
        .replace("#f47b20", BRAND_COLOR)
        .replace("#ff9a4d", BRAND_COLOR_2)
        .replace("MC Growth OS", BRAND_NAME)
        .replace("Growth OS · Lead intelligence", BRAND_TAGLINE)
        .replace("<div>MC Growth <small>", f"<div>{BRAND_COMPANY} <small>")
        .replace('class="mark">MC<', f'class="mark">{BRAND_SHORT}<')
    )


def _firma_sesion(timestamp: str) -> str:
    secreto = os.getenv("DASHBOARD_PASSWORD", "")
    return hmac.new(secreto.encode(), timestamp.encode(), hashlib.sha256).hexdigest()


def _sesion_valida(request: Request) -> bool:
    cookie = request.cookies.get(SESSION_COOKIE, "")
    try:
        timestamp, firma = cookie.split(".", 1)
        vigente = time.time() - int(timestamp) < 60 * 60 * 12
        return vigente and secrets.compare_digest(firma, _firma_sesion(timestamp))
    except (ValueError, TypeError):
        return False


def autenticar_dashboard(request: Request, credentials: HTTPBasicCredentials | None = Depends(security)):
    """Protege el dashboard sin exponer credenciales en el código."""
    usuario = os.getenv("DASHBOARD_USERNAME")
    clave = os.getenv("DASHBOARD_PASSWORD")
    if not usuario or not clave:
        raise HTTPException(status_code=503, detail="Dashboard no configurado: faltan credenciales")
    if _sesion_valida(request):
        return usuario
    usuario_ok = bool(credentials) and secrets.compare_digest(credentials.username, usuario)
    clave_ok = bool(credentials) and secrets.compare_digest(credentials.password, clave)
    if not (usuario_ok and clave_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    logger.info("Base de datos inicializada ✓")
    logger.info(f"Agente Max listo en puerto {PORT} ✓")
    logger.info(f"Proveedor WhatsApp: {proveedor.__class__.__name__} ✓")
    yield


app = FastAPI(
    title="Max — Agente IA comercial",
    description="Agente comercial para calificación de leads y agendamiento de auditorías",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/branding/logo.png")
async def logo_local():
    """
    Logo del cliente servido desde el propio repo — opcional.
    Subí tu archivo a assets/logo.png y poné BRAND_LOGO_URL=/branding/logo.png
    en las variables de entorno. Si preferís un logo alojado afuera, poné esa
    URL directo en BRAND_LOGO_URL y no hace falta tocar este endpoint.
    """
    if not os.path.exists("assets/logo.png"):
        raise HTTPException(status_code=404, detail="No se subió assets/logo.png")
    return FileResponse("assets/logo.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/")
async def health_check():
    """Endpoint de salud para Railway y monitoreo."""
    return {
        "status": "ok",
        "agente": "Max",
        "negocio": cargar_info_negocio().get("negocio", {}).get("nombre", "No configurado"),
        "proveedor": proveedor.__class__.__name__,
        "persistencia": "PostgreSQL" if DATABASE_URL.startswith("postgres") else "SQLite",
        "entorno": ENVIRONMENT,
    }


@app.head("/")
async def health_check_head():
    """HEAD para UptimeRobot — responde 200 sin cuerpo."""
    return PlainTextResponse("", status_code=200)


@app.get("/health/ai")
async def health_ai(request: Request):
    """Healthcheck privado que prueba la conexión real con Claude."""
    secreto = os.getenv("MONITOR_SECRET", "")
    recibido = request.headers.get("x-monitor-secret", "")
    if not secreto or not hmac.compare_digest(recibido, secreto):
        raise HTTPException(status_code=401, detail="No autorizado")
    funciona, detalle = await verificar_ia()
    if not funciona:
        raise HTTPException(status_code=503, detail=detalle)
    return {"status": "ok", "servicio": "claude"}


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """
    Verificación GET del webhook.
    Requerido por Meta Cloud API. No-op para Whapi.cloud.
    """
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


@app.post("/webhook")
async def webhook_handler(request: Request):
    """
    Recibe mensajes de WhatsApp via Whapi.cloud.
    Procesa el mensaje, genera respuesta con Claude y la envía de vuelta.

    Flujo:
    1. Parsear webhook → normalizar mensaje
    2. Obtener historial de conversación
    3. Generar respuesta con Max (Claude)
    4. Guardar en memoria
    5. Enviar respuesta por WhatsApp
    """
    try:
        # Parsear el webhook — el proveedor normaliza el formato
        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            # Los ecos humanos de Coexistence se guardan y pausan Max.
            # Así el comercial puede responder desde WhatsApp Business sin
            # que el bot interrumpa o envíe una segunda respuesta.
            if msg.es_propio:
                if msg.origen == "human" and msg.texto:
                    await guardar_mensaje(msg.telefono, "assistant", msg.texto, fuente="human")
                    await establecer_control_contacto(msg.telefono, False, "Equipo comercial", "Mensaje enviado desde WhatsApp Business")
                    logger.info(f"Toma humana detectada para {msg.telefono}; Max pausado")
                continue
            if not msg.texto:
                continue

            # Toda conversación entra al CRM desde el primer mensaje.
            # El perfil de Meta completa el nombre cuando está disponible.
            nuevo_contacto = await registrar_lead(msg.telefono)
            if nuevo_contacto:
                if msg.nombre_contacto:
                    await actualizar_nombre_lead(msg.telefono, msg.nombre_contacto)
                await cambiar_estado_lead(msg.telefono, "nuevo")
            elif msg.nombre_contacto:
                datos_existentes = next((l for l in await obtener_leads() if l["telefono"] == msg.telefono), None)
                if datos_existentes and datos_existentes.get("nombre") in {"", "No indicó"}:
                    await actualizar_nombre_lead(msg.telefono, msg.nombre_contacto)

            # Marca de actividad + "no leído" — independiente de que Max ya responda
            await registrar_actividad(msg.telefono)

            # Avisar por Telegram que alguien escribió, sin esperar a que califique —
            # así el equipo se entera aunque Max esté pausado para ese contacto
            await notificar_nuevo_mensaje(msg.telefono, msg.texto, msg.nombre_contacto, nuevo_contacto)

            control = await obtener_control_contacto(msg.telefono)
            if not control["bot_activo"] or not BOT_ENABLED:
                await guardar_mensaje(msg.telefono, "user", msg.texto, fuente="user")
                motivo = "apagado globalmente" if not BOT_ENABLED else f"Max pausado para {msg.telefono}"
                logger.info(f"Mensaje guardado sin respuesta: {motivo}")
                continue

            logger.info(f"Mensaje recibido de {msg.telefono}: {msg.texto[:80]}...")
            proveedor_mensaje = proveedor
            if msg.canal_id and proveedor.__class__.__name__ == "ProveedorMeta":
                canal = await obtener_canal(msg.canal_id)
                if canal:
                    from agent.providers.meta import ProveedorMeta
                    proveedor_mensaje = ProveedorMeta(canal.access_token, canal.phone_number_id, canal.verify_token)

            # Obtener historial ANTES de guardar el mensaje actual
            # (evita duplicados — brain.py agrega el mensaje al construir los mensajes)
            historial = await obtener_historial(msg.telefono)

            # Generar respuesta con Claude (Max)
            respuesta = await generar_respuesta(msg.texto, historial)

            # Guardar mensaje del prospecto y respuesta de Max en memoria
            await guardar_mensaje(msg.telefono, "user", msg.texto, fuente="user")
            await guardar_mensaje(msg.telefono, "assistant", respuesta, fuente="bot")

            # Enviar respuesta por WhatsApp via el proveedor
            enviado = await proveedor_mensaje.enviar_mensaje(msg.telefono, respuesta)

            if enviado:
                logger.info(f"Respuesta enviada a {msg.telefono} ✓")
            else:
                logger.warning(f"No se pudo enviar respuesta a {msg.telefono}")

            # Detectar si Max propuso la auditoría gratuita (lead calificado)
            respuesta_normalizada = respuesta.lower()
            LINK_AUDITORIA = "calendar.app.google"
            calificacion_explicita = (
                "calific" in respuesta_normalizada
                and "auditor" in respuesta_normalizada
                and "no calific" not in respuesta_normalizada
            )
            no_calificado = any(frase in respuesta_normalizada for frase in (
                "no calific", "no parece ser el momento", "no sería una buena opción", "no seria una buena opcion",
                "no podemos ayudarte", "fuera de nuestro alcance"
            ))
            if LINK_AUDITORIA in respuesta_normalizada or calificacion_explicita:
                datos_lead = next((l for l in await obtener_leads() if l["telefono"] == msg.telefono), None)
                if datos_lead and not datos_lead.get("notificado"):
                    # Obtener historial completo para extraer info estructurada
                    historial_completo = await obtener_historial(msg.telefono, limite=30)
                    # Extraer datos del lead con Claude Haiku
                    info = await extraer_info_lead(historial_completo)
                    await actualizar_info_lead(
                        msg.telefono,
                        nombre=info.get("nombre", "No indicó"),
                        rubro=info.get("rubro", "No indicó"),
                        presupuesto=info.get("presupuesto", "No indicó"),
                        interes=info.get("interes", "No indicó"),
                        sentiment_score=info.get("sentiment_score", 50),
                        sentiment_label=info.get("sentiment_label", "neutral"),
                        resumen=info.get("resumen", "No disponible"),
                    )
                    await marcar_lead_notificado(msg.telefono)
                    await notificar_lead_calificado(msg.telefono, info)
                    logger.info(f"Lead calificado notificado: {msg.telefono}")
                await cambiar_estado_lead(msg.telefono, "contactado")
            elif no_calificado:
                # Nunca descartamos automáticamente: los casos dudosos quedan
                # en seguimiento y se escalan a la persona responsable.
                await cambiar_estado_lead(msg.telefono, "contactado")
                datos_revision = next((l for l in await obtener_leads() if l["telefono"] == msg.telefono), None)
                if datos_revision and not datos_revision.get("revision_notificada"):
                    historial_revision = await obtener_historial(msg.telefono, limite=30)
                    info_revision = await extraer_info_lead(historial_revision)
                    await actualizar_info_lead(
                        msg.telefono,
                        nombre=info_revision.get("nombre", datos_revision.get("nombre", "No indicó")),
                        rubro=info_revision.get("rubro", datos_revision.get("rubro", "No indicó")),
                        presupuesto=info_revision.get("presupuesto", datos_revision.get("presupuesto", "No indicó")),
                        interes=info_revision.get("interes", datos_revision.get("interes", "No indicó")),
                        sentiment_score=info_revision.get("sentiment_score", 50),
                        sentiment_label=info_revision.get("sentiment_label", "neutral"),
                        resumen=info_revision.get("resumen", "Requiere revisión humana"),
                    )
                    await marcar_revision_notificada(msg.telefono)
                    await notificar_lead_revision(msg.telefono, info_revision)
            elif nuevo_contacto:
                # Cuando Max ya tomó el primer turno, movemos el contacto a contactado.
                await cambiar_estado_lead(msg.telefono, "contactado")

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/instagram/webhook")
async def instagram_verificacion(request: Request):
    from agent.providers.instagram import ProveedorInstagram
    resultado = await ProveedorInstagram().validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    raise HTTPException(status_code=403, detail="Verificación de Instagram inválida")


@app.post("/instagram/webhook")
async def instagram_webhook(request: Request):
    """Recibe DMs de Instagram y los procesa con el mismo Max."""
    from agent.providers.instagram import ProveedorInstagram
    ig = ProveedorInstagram()
    try:
        mensajes = await ig.parsear_webhook(request)
        for msg in mensajes:
            historial = await obtener_historial(msg.telefono)
            respuesta = await generar_respuesta(msg.texto, historial)
            await guardar_mensaje(msg.telefono, "user", msg.texto)
            await guardar_mensaje(msg.telefono, "assistant", respuesta)
            await ig.enviar_mensaje(msg.telefono, respuesta)
            respuesta_normalizada = respuesta.lower()
            calificacion_explicita = (
                "calific" in respuesta_normalizada
                and "auditor" in respuesta_normalizada
                and "no calific" not in respuesta_normalizada
            )
            if "calendar.app.google" in respuesta_normalizada or calificacion_explicita:
                es_nuevo = await registrar_lead(msg.telefono)
                if es_nuevo:
                    info = await extraer_info_lead(await obtener_historial(msg.telefono, limite=30))
                    await actualizar_info_lead(
                        msg.telefono,
                        nombre=info.get("nombre", "No indicó"),
                        rubro=info.get("rubro", "No indicó"),
                        presupuesto=info.get("presupuesto", "No indicó"),
                        interes=info.get("interes", "No indicó"),
                        sentiment_score=info.get("sentiment_score", 50),
                        sentiment_label=info.get("sentiment_label", "neutral"),
                        resumen=info.get("resumen", "No disponible"),
                    )
                    await notificar_lead_calificado(msg.telefono, info)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error en webhook Instagram: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Dashboard de leads ──────────────────────────────────────────────────────

@app.get("/leads")
async def api_leads(_usuario: str = Depends(autenticar_dashboard)):
    """API: lista todos los leads calificados (para el dashboard o integraciones)."""
    leads = await obtener_leads()
    return {"leads": leads, "total": len(leads)}


@app.post("/leads/manual")
async def crear_lead_manual(request: Request, _usuario: str = Depends(autenticar_dashboard)):
    """Crea una oportunidad desde el CRM sin necesidad de una conversación previa."""
    datos = await request.json()
    telefono = str(datos.get("telefono", "")).strip().replace(" ", "").replace("-", "")
    if not telefono or len(telefono) < 6:
        raise HTTPException(status_code=400, detail="Ingresá un teléfono válido")
    if not await registrar_lead(telefono):
        raise HTTPException(status_code=409, detail="Ya existe un lead con ese teléfono")
    await actualizar_info_lead(
        telefono,
        str(datos.get("nombre", "No indicó"))[:100],
        str(datos.get("rubro", "No indicó"))[:100],
        str(datos.get("presupuesto", "No indicó"))[:100],
        str(datos.get("interes", "No indicó"))[:2000],
        int(datos.get("sentiment_score", 50) or 50),
        str(datos.get("sentiment_label", "neutral"))[:30],
        str(datos.get("resumen", "Lead agregado manualmente"))[:4000],
    )
    await actualizar_datos_oportunidad(
        telefono,
        fecha_proxima_accion=str(datos.get("fecha_proxima_accion", "")),
        valor_oportunidad=str(datos.get("valor_oportunidad", "")),
        origen=str(datos.get("origen", "Carga manual")),
    )
    etapa = str(datos.get("etapa", "nuevo")).strip() or "nuevo"
    await cambiar_estado_lead(telefono, etapa)
    return {"status": "ok", "mensaje": "Lead agregado", "telefono": telefono}


@app.get("/leads/{telefono}/conversation")
async def api_conversacion(telefono: str, _usuario: str = Depends(autenticar_dashboard)):
    """API: devuelve todos los mensajes de la conversación del lead. Abrirla cuenta como leída."""
    mensajes = await obtener_conversacion(telefono)
    await marcar_leido(telefono)
    return {"telefono": telefono, "messages": mensajes}


@app.post("/leads/{telefono}/nombre")
async def guardar_nombre_lead(telefono: str, request: Request, _usuario: str = Depends(autenticar_dashboard)):
    datos = await request.json()
    if not await actualizar_nombre_lead(telefono, str(datos.get("nombre", ""))):
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return {"status": "ok"}


@app.post("/leads/{telefono}/reply")
async def responder_desde_crm(telefono: str, request: Request, _usuario: str = Depends(autenticar_dashboard)):
    """Envía una respuesta humana por WhatsApp Cloud API y la guarda en el historial."""
    datos = await request.json()
    mensaje = str(datos.get("mensaje", "")).strip()
    if not mensaje:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")
    proveedor_mensaje = proveedor
    canal_id = str(datos.get("canal_id", "")).strip()
    if canal_id and proveedor.__class__.__name__ == "ProveedorMeta":
        canal = await obtener_canal(canal_id)
        if canal:
            from agent.providers.meta import ProveedorMeta
            proveedor_mensaje = ProveedorMeta(canal.access_token, canal.phone_number_id, canal.verify_token)
    enviado = await proveedor_mensaje.enviar_mensaje(telefono, mensaje)
    if not enviado:
        raise HTTPException(status_code=502, detail="Meta no pudo enviar el mensaje")
    await guardar_mensaje(telefono, "assistant", mensaje, fuente="human")
    await establecer_control_contacto(telefono, False, str(datos.get("responsable", "Equipo comercial"))[:100], "Respuesta enviada desde el CRM")
    return {"status": "ok", "fuente": "human", "bot_activo": False}


@app.get("/conversaciones")
async def api_conversaciones(_usuario: str = Depends(autenticar_dashboard)):
    """API: todos los contactos que hablaron con Max, calificados o no."""
    return {"conversaciones": await obtener_conversaciones()}


def _csv_response(nombre: str, encabezados: list[str], filas: list[list]) -> StreamingResponse:
    """Genera CSV UTF-8 compatible con Excel y Google Sheets."""
    buffer = io.StringIO()
    # El punto y coma permite que Excel en configuración regional argentina
    # distribuya automáticamente cada campo en su propia columna.
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(encabezados)
    writer.writerows(filas)
    contenido = "\ufeff" + buffer.getvalue()
    return StreamingResponse(
        iter([contenido]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@app.get("/export/leads.csv")
async def exportar_leads_csv(_usuario: str = Depends(autenticar_dashboard)):
    """Exporta toda la base de leads sin eliminar ni modificar registros."""
    leads = await obtener_leads()
    filas = []
    for lead in leads:
        estado = "cerrado" if lead["cerrado"] else "descartado" if lead["descartado"] else "seguimiento"
        filas.append([
            lead["telefono"], lead["nombre"], lead["rubro"], lead["presupuesto"],
            lead["interes"], lead["sentiment_score"], lead["sentiment_label"],
            lead["resumen"], lead["nota"], lead["proxima_accion"], lead["valor_oportunidad"], lead["origen"], lead["fecha_proxima_accion"], estado, lead["timestamp"],
        ])
    return _csv_response(
        "mc-growth-leads.csv",
        ["telefono", "nombre", "rubro", "presupuesto", "interes", "sentiment_score", "sentiment_label", "resumen", "nota_interna", "proxima_accion", "valor_oportunidad", "origen", "fecha_proxima_accion", "estado", "fecha"],
        filas,
    )


@app.get("/export/conversaciones.csv")
async def exportar_conversaciones_csv(_usuario: str = Depends(autenticar_dashboard)):
    """Exporta todos los mensajes para respaldo y auditoría."""
    mensajes = await obtener_todos_los_mensajes()
    return _csv_response(
        "mc-growth-conversaciones.csv",
        ["telefono", "role", "mensaje", "fecha"],
        [[m["telefono"], m["role"], m["content"], m["timestamp"]] for m in mensajes],
    )


@app.post("/leads/{telefono}/cerrar")
async def cerrar_lead(telefono: str, _usuario: str = Depends(autenticar_dashboard)):
    """API: marca un lead como cerrado (cliente ganado)."""
    ok = await marcar_lead_cerrado(telefono)
    if not ok:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return {"status": "ok", "mensaje": f"Lead {telefono} marcado como cerrado"}


@app.post("/leads/{telefono}/descartar")
async def descartar_lead(telefono: str, _usuario: str = Depends(autenticar_dashboard)):
    """API: marca un lead como descartado (no avanzó)."""
    ok = await marcar_lead_descartado(telefono)
    if not ok:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return {"status": "ok", "mensaje": f"Lead {telefono} marcado como descartado"}


@app.post("/leads/{telefono}/estado")
async def cambiar_estado(telefono: str, request: Request, _usuario: str = Depends(autenticar_dashboard)):
    datos = await request.json()
    estado = datos.get("estado", "seguimiento")
    if not await cambiar_estado_lead(telefono, estado):
        raise HTTPException(status_code=400, detail="Estado o lead inválido")
    return {"status": "ok", "estado": estado}


@app.post("/leads/{telefono}/calificado")
async def marcar_calificado_endpoint(telefono: str, request: Request, _usuario: str = Depends(autenticar_dashboard)):
    """API: marca o desmarca a mano si un lead califica, para medir conversión del funnel."""
    datos = await request.json()
    calificado = bool(datos.get("calificado", True))
    if not await marcar_calificado(telefono, calificado):
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return {"status": "ok", "calificado": calificado}


@app.post("/leads/{telefono}/seguimiento")
async def guardar_seguimiento(telefono: str, request: Request, _usuario: str = Depends(autenticar_dashboard)):
    """Guarda la nota interna y la próxima acción comercial del lead."""
    datos = await request.json()
    ok = await actualizar_seguimiento_lead(
        telefono,
        nota=str(datos.get("nota", "")),
        proxima_accion=str(datos.get("proxima_accion", "")),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return {"status": "ok"}


@app.post("/leads/{telefono}/oportunidad")
async def guardar_datos_oportunidad(telefono: str, request: Request, _usuario: str = Depends(autenticar_dashboard)):
    """Guarda fecha de seguimiento, valor estimado y origen del lead."""
    datos = await request.json()
    ok = await actualizar_datos_oportunidad(
        telefono,
        fecha_proxima_accion=str(datos.get("fecha_proxima_accion", "")),
        valor_oportunidad=str(datos.get("valor_oportunidad", "")),
        origen=str(datos.get("origen", "")),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return {"status": "ok"}


@app.get("/contacts/{telefono}/control")
async def estado_control_contacto(telefono: str, _usuario: str = Depends(autenticar_dashboard)):
    """Devuelve quién tiene el control de la conversación."""
    return await obtener_control_contacto(telefono)


@app.post("/contacts/{telefono}/takeover")
async def tomar_control_contacto(telefono: str, _usuario: str = Depends(autenticar_dashboard)):
    """Pausa Max para que el equipo continúe desde WhatsApp Business."""
    return {"status": "ok", **await establecer_control_contacto(telefono, False, "Equipo comercial", "Toma manual desde el dashboard")}


@app.post("/contacts/{telefono}/resume")
async def reactivar_max_contacto(telefono: str, _usuario: str = Depends(autenticar_dashboard)):
    """Reactiva Max para ese contacto, sin borrar el historial."""
    return {"status": "ok", **await establecer_control_contacto(telefono, True)}


@app.delete("/leads/{telefono}")
async def eliminar_lead_api(telefono: str, _usuario: str = Depends(autenticar_dashboard)):
    """Elimina un lead y su conversación sólo mediante una acción explícita."""
    if not await eliminar_lead(telefono):
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return {"status": "ok", "mensaje": "Lead y conversación eliminados"}


@app.get("/api/channels")
async def api_channels(_usuario: str = Depends(autenticar_dashboard)):
    canales = await obtener_canales()
    return {"bot_enabled": BOT_ENABLED, "channels": canales, "other_channels": [
        {"id": "instagram", "name": "Instagram", "status": "not_configured", "available": False},
        {"id": "facebook", "name": "Facebook Messenger", "status": "not_configured", "available": False},
        {"id": "linkedin", "name": "LinkedIn", "status": "not_configured", "available": False},
    ]}


@app.get("/api/system/status")
async def api_system_status(_usuario: str = Depends(autenticar_dashboard)):
    """Estado operativo sin exponer credenciales ni la URL de conexión."""
    return {
        "status": "ok",
        "persistencia": "PostgreSQL" if DATABASE_URL.startswith("postgres") else "SQLite",
        "entorno": ENVIRONMENT,
        "bot": "activo" if BOT_ENABLED else "pausado",
    }


@app.get("/api/settings")
async def api_settings(_usuario: str = Depends(autenticar_dashboard)):
    """Configuración editable del workspace para el panel autogestionable."""
    return await obtener_configuracion()


@app.put("/api/settings")
async def update_settings(payload: dict, _usuario: str = Depends(autenticar_dashboard)):
    """Guarda etapas, nombres y campos desde el CRM, sin tocar el código."""
    pipeline = payload.get("pipeline", {})
    etapas = pipeline.get("etapas", [])
    if etapas:
        keys = [str(item.get("key", "")).strip() for item in etapas]
        if len(keys) != len(set(keys)) or any(not key.replace("_", "").isalnum() for key in keys):
            raise HTTPException(status_code=400, detail="Las etapas deben tener identificadores únicos válidos")
        if len(etapas) > 10:
            raise HTTPException(status_code=400, detail="El pipeline admite hasta 10 etapas")
    campos = pipeline.get("campos", [])
    if len(campos) > 20:
        raise HTTPException(status_code=400, detail="Se permiten hasta 20 campos configurables")
    return await guardar_configuracion({"pipeline": {"etapas": etapas, "campos": campos}, "workspace": payload.get("workspace", {})})


@app.get("/api/meta/embedded-signup/config")
async def embedded_signup_config(_usuario: str = Depends(autenticar_dashboard)):
    """Devuelve sólo datos públicos necesarios para abrir el diálogo de Meta."""
    return {
        "app_id": os.getenv("META_APP_ID", "1016554401027275"),
        "config_id": os.getenv("META_EMBEDDED_SIGNUP_CONFIG_ID", "1398042952535570"),
        "version": "v26.0",
    }


@app.post("/api/channels")
async def crear_canal(payload: dict, _usuario: str = Depends(autenticar_dashboard)):
    if payload.get("tipo") != "whatsapp" or not all(payload.get(k) for k in ("nombre", "phone_number_id", "access_token")):
        raise HTTPException(status_code=400, detail="Para WhatsApp se requiere nombre, Phone Number ID y token")
    return await guardar_canal(payload["nombre"], "whatsapp", payload["phone_number_id"], payload["access_token"], payload.get("verify_token", os.getenv("META_VERIFY_TOKEN", "mcgrowth-webhook-2026")))


@app.post("/api/channels/whatsapp/toggle")
async def toggle_whatsapp(_usuario: str = Depends(autenticar_dashboard)):
    # Declarado ANTES de /api/channels/{canal_id}/toggle a propósito: si va
    # después, esa ruta genérica intercepta "whatsapp" como si fuera un
    # canal_id numérico y nunca llega acá (FastAPI matchea por orden).
    global BOT_ENABLED
    BOT_ENABLED = not BOT_ENABLED
    return {"status": "ok", "enabled": BOT_ENABLED}


@app.post("/api/channels/{canal_id}/toggle")
async def toggle_canal(canal_id: int, _usuario: str = Depends(autenticar_dashboard)):
    return {"status": "ok", "activo": await alternar_canal(canal_id)}


@app.post("/api/demo/seed")
async def seed_demo_data(_usuario: str = Depends(autenticar_dashboard)):
    """Crea leads ficticios para probar el dashboard. No usa datos reales."""
    demos = [
        ("5491100000001", "Lucía Demo", "Desarrolladora inmobiliaria", "USD 1.000/mes", "Más leads calificados para un lanzamiento", 84, "positivo", "Tiene campaña activa y busca mejorar la calidad de sus consultas.", "seguimiento"),
        ("5491100000002", "Tomás Demo", "Inmobiliaria", "USD 700/mes", "Automatizar la respuesta inicial", 67, "positivo", "Cuenta con equipo comercial y quiere implementar pronto.", "cerrado"),
        ("5491100000003", "Sofía Demo", "Estudio de arquitectura", "No indicó", "Landing de conversión", 48, "neutral", "Está explorando alternativas para más adelante.", "descartado"),
    ]
    creados = 0
    for telefono, nombre, rubro, presupuesto, interes, score, etiqueta, resumen, estado in demos:
        if await registrar_lead(telefono):
            await actualizar_info_lead(telefono, nombre, rubro, presupuesto, interes, score, etiqueta, resumen)
            await guardar_mensaje(telefono, "user", f"Hola, soy {nombre}. Necesito ayuda para conseguir más oportunidades.")
            await guardar_mensaje(telefono, "assistant", "¡Hola! Cuéntame un poco sobre tu negocio y qué objetivo quieres lograr.")
            await guardar_mensaje(telefono, "user", f"Somos una {rubro.lower()} y nos interesa {interes.lower()}.")
            await cambiar_estado_lead(telefono, estado)
            creados += 1
    return {"status": "ok", "creados": creados, "mensaje": "Datos demo listos"}


@app.get("/dashboard-old", response_class=HTMLResponse)
async def dashboard(_usuario: str = Depends(autenticar_dashboard)):
    """Dashboard web en tiempo real — leads calificados por Max."""
    leads = await obtener_leads()
    total = len(leads)
    en_seguimiento = sum(1 for l in leads if not l["cerrado"] and not l["descartado"])
    cerrados = sum(1 for l in leads if l["cerrado"])
    descartados = sum(1 for l in leads if l["descartado"])
    tasa = round(cerrados / (total - descartados) * 100) if (total - descartados) > 0 else 0

    filas = ""
    for lead in leads:
        tel = lead["telefono"].replace("@s.whatsapp.net", "").replace("@c.us", "")
        fecha = lead["timestamp"][:16].replace("T", " ")

        nombre = lead.get("nombre", "—")
        rubro = lead.get("rubro", "—")
        presupuesto = lead.get("presupuesto", "—")
        interes = lead.get("interes", "—")

        if lead["cerrado"]:
            estado = "Cerrado"
            color = "#22c55e"
            botones = ""
        elif lead["descartado"]:
            estado = "Descartado"
            color = "#64748b"
            botones = ""
        else:
            estado = "En seguimiento"
            color = "#f59e0b"
            botones = (
                f'<button onclick="cerrar(\'{lead["telefono"]}\')" '
                f'style="background:#22c55e;color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;margin-right:6px;">Cerrado</button>'
                f'<button onclick="descartar(\'{lead["telefono"]}\')" '
                f'style="background:#475569;color:white;border:none;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:13px;">Descartar</button>'
            )

        filas += f"""
        <tr>
          <td style="padding:12px 16px;">+{tel}<br><span style="color:#64748b;font-size:12px;">{nombre}</span></td>
          <td style="padding:12px 16px;">{rubro}</td>
          <td style="padding:12px 16px;">{presupuesto}</td>
          <td style="padding:12px 16px;max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="{interes}">{interes}</td>
          <td style="padding:12px 16px;">{fecha}<br><span style="background:{color};color:white;padding:2px 8px;border-radius:10px;font-size:11px;">{estado}</span></td>
          <td style="padding:12px 16px;">{botones}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard — Max</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
    .header {{ background: #1e293b; padding: 24px 32px; border-bottom: 1px solid #334155; }}
    .header h1 {{ font-size: 22px; font-weight: 700; color: #f1f5f9; }}
    .header p {{ color: #94a3b8; font-size: 14px; margin-top: 4px; }}
    .stats {{ display: flex; gap: 16px; padding: 24px 32px; flex-wrap: wrap; }}
    .stat {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px 24px; flex: 1; min-width: 140px; }}
    .stat .num {{ font-size: 36px; font-weight: 800; color: #f1f5f9; }}
    .stat .label {{ color: #94a3b8; font-size: 13px; margin-top: 4px; }}
    .table-wrap {{ margin: 0 32px 32px; background: #1e293b; border: 1px solid #334155; border-radius: 12px; overflow: hidden; }}
    table {{ width: 100%; border-collapse: collapse; }}
    thead tr {{ background: #0f172a; }}
    th {{ padding: 12px 16px; text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; }}
    tbody tr {{ border-top: 1px solid #334155; }}
    tbody tr:hover {{ background: #0f172a; }}
    .refresh {{ margin: 0 32px 24px; color: #64748b; font-size: 13px; }}
    a {{ color: #60a5fa; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="header">
    <h1>Max — Dashboard de Leads</h1>
    <p>Actualizacion automatica cada 30 segundos</p>
  </div>
  <div class="stats">
    <div class="stat"><div class="num">{total}</div><div class="label">Leads calificados</div></div>
    <div class="stat"><div class="num" style="color:#f59e0b;">{en_seguimiento}</div><div class="label">En seguimiento</div></div>
    <div class="stat"><div class="num" style="color:#22c55e;">{cerrados}</div><div class="label">Cerrados</div></div>
    <div class="stat"><div class="num" style="color:#64748b;">{descartados}</div><div class="label">Descartados</div></div>
    <div class="stat"><div class="num" style="color:#60a5fa;">{tasa}%</div><div class="label">Tasa de conversion</div></div>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>WhatsApp</th><th>Rubro</th><th>Presupuesto ads</th><th>Interes</th><th>Fecha / Estado</th><th>Acciones</th></tr></thead>
      <tbody>{filas if filas else '<tr><td colspan="6" style="padding:32px;text-align:center;color:#64748b;">Sin leads aun. Max esta listo para calificar.</td></tr>'}</tbody>
    </table>
  </div>
  <p class="refresh">Ultima actualizacion: {leads[0]["timestamp"][:16].replace("T", " ") if leads else "—"} · <a href="/dashboard">Actualizar</a></p>
  <script>
    async function cerrar(telefono) {{
      if (!confirm('Marcar como Cerrado (cliente ganado)?')) return;
      const r = await fetch('/leads/' + encodeURIComponent(telefono) + '/cerrar', {{method: 'POST'}});
      if (r.ok) location.reload();
      else alert('Error');
    }}
    async function descartar(telefono) {{
      if (!confirm('Marcar como Descartado (no avanzo)?')) return;
      const r = await fetch('/leads/' + encodeURIComponent(telefono) + '/descartar', {{method: 'POST'}});
      if (r.ok) location.reload();
      else alert('Error');
    }}
    setTimeout(() => location.reload(), 30000);
  </script>
</body>
</html>"""
    return html


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    html = """<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Acceso · MC Growth OS</title><style>body{margin:0;background:#09090b;color:#f4f4f5;font:14px system-ui;display:grid;place-items:center;min-height:100vh}.box{width:min(360px,calc(100% - 40px));background:#111113;border:1px solid #27272a;border-radius:16px;padding:28px}.mark{display:inline-block;background:#f47b20;color:#09090b;border-radius:9px;padding:9px;font-weight:900;margin-bottom:16px}h1{font-size:22px;margin:0 0 6px}p{color:#a1a1aa;margin:0 0 22px}label{display:block;color:#a1a1aa;font-size:12px;margin:13px 0 6px}input{width:100%;padding:11px;border-radius:8px;border:1px solid #3f3f46;background:#18181b;color:#fff;box-sizing:border-box}button{width:100%;margin-top:20px;padding:11px;border:0;border-radius:8px;background:#f47b20;color:#09090b;font-weight:800;cursor:pointer}</style></head><body><form class="box" method="post"><div class="mark">MC</div><h1>MC Growth OS</h1><p>Ingresá para ver tus oportunidades.</p><label>Usuario</label><input name="usuario" autocomplete="username" required><label>Contraseña</label><input name="clave" type="password" autocomplete="current-password" required><button>Ingresar al dashboard</button></form></body></html>"""
    return HTMLResponse(_marca(html))


@app.post("/login")
async def login(usuario: str = Form(...), clave: str = Form(...)):
    esperado_usuario = os.getenv("DASHBOARD_USERNAME", "")
    esperado_clave = os.getenv("DASHBOARD_PASSWORD", "")
    if not esperado_usuario or not esperado_clave or not secrets.compare_digest(usuario, esperado_usuario) or not secrets.compare_digest(clave, esperado_clave):
        return HTMLResponse("<p style='font-family:system-ui;padding:30px'>Usuario o contraseña incorrectos. <a href='/login'>Volver</a></p>", status_code=401)
    timestamp = str(int(time.time()))
    response = RedirectResponse("/dashboard", status_code=303)
    # El navegador embebido puede no conservar cookies marcadas como Secure;
    # el transporte sigue protegido por HTTPS en Render.
    response.set_cookie(SESSION_COOKIE, timestamp + "." + _firma_sesion(timestamp), httponly=True, secure=False, samesite="lax", max_age=60 * 60 * 12)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_v2(request: Request):
    if not _sesion_valida(request):
        return RedirectResponse("/login", status_code=303)
    """Dashboard CRM: pipeline, conversaciones, sentimiento y canales."""
    response = HTMLResponse("""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MC Growth OS</title><style>
:root{--bg:#09090b;--p:#111113;--p2:#18181b;--l:#27272a;--t:#f4f4f5;--m:#a1a1aa;--o:#f47b20;--o2:#ff9a4d;--blue:#3b82f6}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:radial-gradient(ellipse at 15% -10%,rgba(244,123,32,.13),transparent 38%),radial-gradient(ellipse at 90% 0%,rgba(59,130,246,.11),transparent 30%),var(--bg);color:var(--t);font:14px 'Geist',system-ui,sans-serif;min-height:100vh}.top{height:70px;border-bottom:1px solid var(--l);display:flex;justify-content:space-between;align-items:center;padding:0 30px;background:rgba(9,9,11,.82);backdrop-filter:blur(16px);position:sticky;top:0;z-index:4}.brand{display:flex;align-items:center;gap:12px;font-weight:800;letter-spacing:-.02em}.mark{background:linear-gradient(135deg,var(--o),var(--o2));color:#09090b;border-radius:9px;padding:9px;font-weight:900;box-shadow:0 0 24px rgba(244,123,32,.25)}.brand small{display:block;color:var(--m);font-size:11px;font-weight:400;letter-spacing:0}.live{color:#86efac;background:#052e16;padding:7px 11px;border-radius:99px;font-size:12px}.wrap{max-width:1500px;margin:auto;padding:28px 30px;position:relative}.wrap:before{content:'';position:absolute;inset:0;pointer-events:none;opacity:.22;background-image:radial-gradient(circle at 20% 20%,#fff 0 1px,transparent 1.5px),radial-gradient(circle at 80% 35%,var(--o2) 0 1px,transparent 1.5px),radial-gradient(circle at 55% 75%,#fff 0 1px,transparent 1.5px);background-size:180px 160px,260px 220px,320px 280px;animation:drift 18s linear infinite}@keyframes drift{to{background-position:40px 25px,-30px 45px,20px -35px}}.intro,.tabs,.panel{position:relative}.intro h1{margin:0 0 5px;font-size:28px;letter-spacing:-.04em}.intro p{margin:0;color:var(--m)}.tabs{display:flex;gap:5px;border-bottom:1px solid var(--l);margin:25px 0 20px}.tab{background:none;color:var(--m);padding:11px 16px;border-bottom:2px solid transparent}.tab.active{color:var(--t);border-color:var(--o)}.panel{display:none}.panel.active{display:block}.stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:22px}.stat,.channel,.card{background:rgba(17,17,19,.88);border:1px solid var(--l);border-radius:14px}.stat{padding:17px;transition:transform .2s,border-color .2s}.stat:hover,.channel:hover,.card:hover{transform:translateY(-2px);border-color:rgba(244,123,32,.35)}.stat b{font-size:28px;display:block}.stat span{color:var(--m);font-size:12px}.pipeline{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.stage{background:rgba(14,14,16,.82);border:1px solid var(--l);border-radius:14px;padding:13px;min-height:280px}.stage h3{font-size:13px;margin:0 0 13px;display:flex;justify-content:space-between}.stage h3 span{color:var(--m)}.stage[data-stage=seguimiento] h3{color:#fbbf24}.stage[data-stage=cerrado] h3{color:#86efac}.stage[data-stage=descartado] h3{color:#a1a1aa}.card{padding:14px;margin-bottom:10px}.cardtop{display:flex;justify-content:space-between;gap:8px}.name{font-weight:700}.phone{color:var(--m);font-size:12px;margin-top:3px}.pill{font-size:11px;padding:4px 7px;border-radius:99px;background:#27272a}.positive{background:#86efac;color:#09090b}.neutral{background:#fde68a;color:#09090b}.negative{background:#fca5a5;color:#09090b}.data{margin:12px 0;line-height:1.5;font-size:12px}.data strong{color:#fff}.muted{color:var(--m)}.actions{display:flex;gap:7px;flex-wrap:wrap}.actions button,.connect{border:0;border-radius:8px;padding:7px 10px;background:#3f3f46;color:#fff;font-size:12px;cursor:pointer}.win{background:#166534!important}.lose{background:#3f3f46!important}.empty{text-align:center;color:#52525b;padding:35px 5px;font-size:12px}.channels{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.channel{padding:18px;transition:transform .2s,border-color .2s}.channel h3{margin:11px 0 4px}.channel p{color:var(--m);font-size:12px;line-height:1.5;min-height:36px}.icon{font-size:25px}.status{color:#86efac;font-size:11px}.status.off{color:var(--m)}.connect{width:100%;background:linear-gradient(135deg,var(--o),var(--o2));color:#09090b;font-weight:700}.connect.off{background:#27272a;color:#fff}.note{margin-top:18px;padding:14px;color:var(--m);border:1px solid var(--l);border-radius:12px;font-size:12px;line-height:1.5}.overlay{display:none;position:fixed;inset:0;background:#000b;z-index:5;padding:5vh 4vw}.modal{max-width:760px;max-height:90vh;overflow:auto;margin:auto;background:var(--p);border:1px solid var(--l);border-radius:14px;padding:22px}.modalhead{display:flex;justify-content:space-between;border-bottom:1px solid var(--l);padding-bottom:14px}.close{background:none;color:var(--m);font-size:22px}.chat{padding-top:16px;display:flex;flex-direction:column;gap:10px}.bubble{max-width:82%;padding:10px 13px;border-radius:13px;white-space:pre-wrap;line-height:1.45}.bubble.user{background:#27272a}.bubble.assistant{align-self:flex-end;background:#7c3f12}.time{display:block;color:var(--m);font-size:10px;margin-top:5px}@media(max-width:900px){.stats{grid-template-columns:repeat(2,1fr)}.pipeline{grid-template-columns:1fr}.channels{grid-template-columns:repeat(2,1fr)}.wrap{padding:22px 15px}}@media(max-width:520px){.channels{grid-template-columns:1fr}}
</style></head><body><header class="top"><div class="brand"><div class="mark">MC</div><div>MC Growth <small>Growth OS · Lead intelligence</small></div></div><div class="live">● Max operativo</div></header><main class="wrap"><section class="intro"><h1>Pipeline de oportunidades</h1><p>Convertí conversaciones en decisiones comerciales.</p></section><nav class="tabs"><button class="tab active" data-tab="pipeline">Pipeline</button><button class="tab" data-tab="canales">Canales</button></nav><section id="pipeline" class="panel active"><div class="stats"><div class="stat"><b id="total">0</b><span>Leads calificados</span></div><div class="stat"><b id="seguimiento" style="color:#fbbf24">0</b><span>En seguimiento</span></div><div class="stat"><b id="cerrado" style="color:#86efac">0</b><span>Cerrados</span></div><div class="stat"><b id="descartado">0</b><span>Descartados</span></div><div class="stat"><b id="conversion" style="color:#f47b20">0%</b><span>Conversión</span></div></div><div class="pipeline"><div class="stage" data-stage="seguimiento"><h3>En seguimiento <span id="count-seguimiento">0</span></h3><div id="col-seguimiento"></div></div><div class="stage" data-stage="cerrado"><h3>Cerrados <span id="count-cerrado">0</span></h3><div id="col-cerrado"></div></div><div class="stage" data-stage="descartado"><h3>Descartados <span id="count-descartado">0</span></h3><div id="col-descartado"></div></div></div><div class="note">Arrastrá una tarjeta entre columnas. Abrí un lead para ver la conversación completa que tuvo con Max.</div></section><section id="canales" class="panel"><div id="global-bot-toggle" style="margin-bottom:14px"></div><div class="channels" id="channels"></div><div class="note"><strong>Canales:</strong> WhatsApp está conectado a Meta Cloud API. Instagram y Facebook requieren sus Webhooks de Meta; LinkedIn requiere permisos específicos.</div></section></main><div class="overlay" id="overlay"><div class="modal"><div class="modalhead"><div><h2 id="modal-title" style="margin:0 0 4px">Conversación</h2><span id="modal-sub" class="muted"></span></div><button class="close" onclick="closeModal()">×</button></div><div class="chat" id="chat"></div></div></div><script>
const esc=s=>String(s||'').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
let leads=[]; function stage(l){return l.etapa||(l.cerrado?'cerrado':l.descartado?'descartado':'seguimiento')}
function card(l){var s=stage(l),score=l.sentiment_score||50,toggle=l.bot_activo===false?'<button class="resume-max" data-tel="'+esc(l.telefono)+'">Prender Max</button>':'<button class="takeover" data-tel="'+esc(l.telefono)+'">Apagar Max</button>';return '<article class="card" draggable="true" data-tel="'+esc(l.telefono)+'"><div class="cardtop"><div><div class="name">'+esc(l.nombre||'Sin nombre')+'</div><div class="phone">+'+esc(l.telefono.replace('@s.whatsapp.net','').replace('@c.us',''))+'</div></div><span class="pill '+esc(l.sentiment_label||'neutral')+'">'+score+'/100</span></div><div class="data"><div><strong>Rubro:</strong> '+esc(l.rubro)+'</div><div><strong>Presupuesto:</strong> '+esc(l.presupuesto)+'</div><div><strong>Interés:</strong> '+esc(l.interes)+'</div><div class="muted">'+esc(l.resumen)+'</div></div><div class="actions"><button class="open-chat" data-tel="'+esc(l.telefono)+'">Ver chat</button>'+toggle+(s==='seguimiento'?'<button class="win close-lead" data-tel="'+esc(l.telefono)+'">Cerrar</button><button class="discard-lead" data-tel="'+esc(l.telefono)+'">Descartar</button>':'')+'<button class="delete-lead" data-tel="'+esc(l.telefono)+'">Eliminar</button></div></article>'}
async function load(){var d=await (await fetch('/leads')).json(); leads=d.leads||[]; ['seguimiento','cerrado','descartado'].forEach(function(s){var a=leads.filter(function(l){return stage(l)===s}),el=document.getElementById('col-'+s);el.innerHTML=a.length?a.map(card).join(''):'<div class="empty">Sin leads</div>';document.getElementById('count-'+s).textContent=a.length});document.getElementById('total').textContent=leads.length;document.getElementById('seguimiento').textContent=leads.filter(function(l){return stage(l)==='seguimiento'}).length;document.getElementById('cerrado').textContent=leads.filter(function(l){return stage(l)==='cerrado'}).length;document.getElementById('descartado').textContent=leads.filter(function(l){return stage(l)==='descartado'}).length;var base=leads.length-leads.filter(function(l){return l.descartado}).length;document.getElementById('conversion').textContent=(base?Math.round(leads.filter(function(l){return l.cerrado}).length/base*100):0)+'%';document.querySelectorAll('.card').forEach(function(c){c.addEventListener('dragstart',function(e){e.dataTransfer.setData('tel',c.dataset.tel)})});document.querySelectorAll('.stage').forEach(function(c){c.ondragover=function(e){e.preventDefault()};c.ondrop=function(e){setStatus(encodeURIComponent(e.dataTransfer.getData('tel')),c.dataset.stage)}})}
async function setStatus(t,e){var r=await fetch('/leads/'+t+'/estado',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({estado:e})});if(r.ok)load()}
var activeChatPhone='';async function openChat(t,n){activeChatPhone=decodeURIComponent(t);var d=await (await fetch('/leads/'+t+'/conversation')).json();document.getElementById('modal-title').textContent=n;document.getElementById('chat').innerHTML=(d.messages||[]).map(function(m){var label=m.fuente==='human'?'Comercial':m.fuente==='bot'?'Max':'Lead';return '<div class="bubble '+m.role+' '+(m.fuente||'')+'"><small class="bubble-label">'+label+'</small>'+esc(m.content)+'<span class="time">'+new Date(m.timestamp).toLocaleString('es-AR')+'</span></div>'}).join('')||'<div class="empty">No hay mensajes.</div>';document.getElementById('overlay').style.display='block';var leadAbierto=(typeof leads!=='undefined'?leads:[]).find(function(x){return x.telefono===activeChatPhone});if(leadAbierto){leadAbierto.no_leido=false;if(window.updateUnreadBadges)window.updateUnreadBadges();if(window.renderSales)window.renderSales();if(typeof loadInbox==='function'&&document.getElementById('inbox')&&document.getElementById('inbox').classList.contains('active'))loadInbox()}}async function sendHumanReply(){var field=document.getElementById('human-reply'),mensaje=field.value.trim();if(!activeChatPhone||!mensaje)return;var button=document.getElementById('send-human-reply');button.disabled=true;var r=await fetch('/leads/'+encodeURIComponent(activeChatPhone)+'/reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mensaje:mensaje,responsable:'Equipo comercial'})});button.disabled=false;if(r.ok){field.value='';await openChat(encodeURIComponent(activeChatPhone),document.getElementById('modal-title').textContent)}else{var d=await r.json();alert(d.detail||'No se pudo enviar el mensaje')}}function closeModal(){document.getElementById('overlay').style.display='none'}
async function loadChannels(){var d=await (await fetch('/api/channels')).json();var gb=document.getElementById('global-bot-toggle');if(gb)gb.innerHTML='<div class="channel" style="display:flex;justify-content:space-between;align-items:center;gap:14px"><div><h3 style="margin:0 0 4px">Max — '+(d.bot_enabled?'activo':'pausado globalmente')+'</h3><p style="margin:0">'+(d.bot_enabled?'Responde en todos los números conectados.':'No responde a nadie, pero vos seguís recibiendo los avisos de Telegram de cada mensaje nuevo.')+'</p></div><button id="global-bot-btn" class="connect" style="width:auto;'+(d.bot_enabled?'':'background:#27272a;color:#fff')+'">'+(d.bot_enabled?'Pausar Max':'Reactivar Max')+'</button></div>';var html=(d.channels||[]).map(function(c){var on=c.activo&&d.bot_enabled;return '<div class="channel"><div class="icon">W</div><h3>'+esc(c.nombre)+'</h3><div class="status '+(on?'':'off')+'">● '+(on?'Conectado':'Pausado')+'</div><p>WhatsApp Cloud API · '+esc(c.phone_number_id)+'</p><button class="connect channel-action '+(on?'':'off')+'" data-channel-id="'+c.id+'">'+(on?'Desconectar':'Conectar')+'</button></div>'}).join('');html+='<div class="channel"><div class="icon">＋</div><h3>Agregar WhatsApp</h3><div class="status off">● Nuevo número</div><p>Conectá otro Phone Number ID de Meta.</p><button class="connect channel-add">Agregar número</button></div><div class="channel"><div class="icon">↔</div><h3>WhatsApp Coexistence</h3><div class="status off">● Vincular app existente</div><p>Conservá el WhatsApp Business del equipo y probá la conexión oficial de Meta.</p><button class="connect embedded-signup">Conectar con Meta</button></div>';html+=(d.other_channels||[]).map(function(c){return '<div class="channel"><div class="icon">'+c.name[0]+'</div><h3>'+c.name+'</h3><div class="status off">● Próximamente</div><p>Requiere credenciales y Webhook.</p><button class="connect off" disabled>Próximamente</button></div>'}).join('');document.getElementById('channels').innerHTML=html}
async function channelAction(id){await fetch('/api/channels/'+id+'/toggle',{method:'POST'});loadChannels()}
async function addChannel(){var old=document.getElementById('channel-dialog');if(old)old.remove();var box=document.createElement('div');box.id='channel-dialog';box.className='crm-manual-dialog';box.innerHTML='<div class="crm-manual-card" style="max-width:560px"><div class="modalhead"><div><h2 style="margin:0 0 4px">Conectar WhatsApp</h2><span class="muted">Agregá un número de Meta Cloud API y asignale un nombre interno.</span></div><button id="close-channel" class="close">×</button></div><div class="crm-form-grid" style="margin-top:18px"><label>Nombre del canal<input id="channel-name" placeholder="Ej: Ventas Inmobiliarias" required></label><label>Phone Number ID<input id="channel-phone" placeholder="ID de Meta" required></label><label class="crm-form-wide">Token permanente de Meta<input id="channel-token" type="password" placeholder="Pegalo aquí; no se mostrará después" required></label></div><div class="crm-note" style="margin-top:14px;color:#a1a1aa;font-size:12px;line-height:1.5">Este formulario conecta números de Cloud API. La coexistencia con WhatsApp Business del celular depende de la elegibilidad de Meta para ese número.</div><div class="crm-form-actions"><button id="cancel-channel" class="actions button">Cancelar</button><button id="save-channel" class="connect" style="width:auto">Conectar número</button></div></div>';document.body.appendChild(box);var close=function(){box.remove()};document.getElementById('close-channel').onclick=close;document.getElementById('cancel-channel').onclick=close;document.getElementById('save-channel').onclick=async function(){var nombre=document.getElementById('channel-name').value.trim(),phone=document.getElementById('channel-phone').value.trim(),token=document.getElementById('channel-token').value.trim();if(!nombre||!phone||!token){alert('Completá los tres campos');return}var r=await fetch('/api/channels',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nombre:nombre,tipo:'whatsapp',phone_number_id:phone,access_token:token})});if(!r.ok){var d=await r.json();alert(d.detail||'No se pudo guardar el canal');return}close();alert('Número agregado correctamente');loadChannels()}}
document.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;var t=b.dataset.tel;if(b.classList.contains('open-chat')){var l=leads.find(function(x){return x.telefono===t});openChat(encodeURIComponent(t),l?(l.nombre||t):t)}if(b.classList.contains('close-lead'))setStatus(encodeURIComponent(t),'cerrado');if(b.classList.contains('discard-lead'))setStatus(encodeURIComponent(t),'descartado')});
document.addEventListener('click',async function(e){var b=e.target.closest('.takeover,.resume-max');if(!b)return;var t=encodeURIComponent(b.dataset.tel),path=b.classList.contains('takeover')?'takeover':'resume';var r=await fetch('/contacts/'+t+'/'+path,{method:'POST'});if(r.ok){alert(path==='takeover'?'Max pausado. El comercial puede continuar desde WhatsApp Business.':'Max reactivado para este contacto.');load()}else alert('No se pudo actualizar el control de la conversación')});
document.addEventListener('click',async function(e){var b=e.target.closest('.delete-lead');if(!b)return;if(!confirm('Eliminar definitivamente este lead y toda su conversación? Esta acción no se puede deshacer.'))return;var r=await fetch('/leads/'+encodeURIComponent(b.dataset.tel),{method:'DELETE'});if(r.ok)load();else alert('No se pudo eliminar el lead')});
document.addEventListener('click',function(e){if(e.target.closest('.channel-add'))addChannel();var b=e.target.closest('.channel-action');if(b)channelAction(b.dataset.channelId)});
document.addEventListener('click',async function(e){if(!e.target.closest('#global-bot-btn'))return;await fetch('/api/channels/whatsapp/toggle',{method:'POST'});loadChannels()});
var embeddedSignupPromise=null;
function prepararEmbeddedSignup(){if(embeddedSignupPromise)return embeddedSignupPromise;embeddedSignupPromise=(async function(){var cfg=await (await fetch('/api/meta/embedded-signup/config',{cache:'no-store'})).json();if(!window.FB){await new Promise(function(resolve,reject){var s=document.createElement('script');s.src='https://connect.facebook.net/en_US/sdk.js';s.onload=resolve;s.onerror=function(){reject(new Error('El navegador no pudo cargar el SDK de Meta'))};document.head.appendChild(s)});if(!window.FB)throw new Error('El SDK de Meta no quedó disponible');window.FB.init({appId:cfg.app_id,cookie:true,xfbml:false,version:cfg.version})}return cfg})().catch(function(err){embeddedSignupPromise=null;throw err});return embeddedSignupPromise}
function abrirEmbeddedSignup(){prepararEmbeddedSignup().then(function(cfg){if(!window.FB||typeof window.FB.login!=='function')throw new Error('El SDK de Meta no está disponible en este navegador');window.FB.login(function(response){if(response.authResponse&&response.authResponse.code){alert('Meta autorizó el flujo. Estamos listos para completar el intercambio seguro en el servidor.')}else if(response.authResponse){alert('Meta respondió, pero no devolvió código de autorización. Revisemos el flujo.')}else{alert('La vinculación fue cancelada o Meta no la habilitó para esta cuenta.')}},{config_id:cfg.config_id,response_type:'code',override_default_response_type:true,extras:{feature:'whatsapp_embedded_signup',sessionInfoVersion:'3'}})}).catch(function(err){alert('No se pudo abrir Meta: '+err.message+' Probá desde Chrome o Edge si estás dentro del navegador interno.')})}
prepararEmbeddedSignup();
document.addEventListener('click',function(e){if(e.target.closest('.embedded-signup'))abrirEmbeddedSignup()});
document.addEventListener('click',function(e){var b=e.target.closest('.open-inbox-chat');if(b){var l=leads.find(function(x){return x.telefono===b.dataset.tel});openChat(encodeURIComponent(b.dataset.tel),l?(l.nombre||b.dataset.tel):b.dataset.tel)}});
function renderInsights(){var box=document.getElementById('insights');if(!box){document.querySelector('#pipeline .stats').insertAdjacentHTML('afterend','<section id="insights" aria-label="Resumen visual" style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:0 0 22px"></section>');box=document.getElementById('insights')}var total=leads.length,avg=total?Math.round(leads.reduce(function(a,l){return a+(Number(l.sentiment_score)||50)},0)/total):0,pos=leads.filter(function(l){return l.sentiment_label==='positivo'}).length,neu=leads.filter(function(l){return l.sentiment_label==='neutral'}).length,neg=leads.filter(function(l){return l.sentiment_label==='negativo'}).length,max=Math.max(pos,neu,neg,1);box.innerHTML='<div style="background:rgba(17,17,19,.88);border:1px solid #27272a;border-radius:14px;padding:16px"><div style="color:#a1a1aa;font-size:11px;text-transform:uppercase;letter-spacing:1px">Sentimiento promedio</div><strong style="display:block;font-size:28px;color:'+(avg>=70?'#86efac':avg>=45?'#fbbf24':'#fca5a5')+'">'+avg+'/100</strong><span style="color:#a1a1aa;font-size:12px">Lectura general de los leads</span></div><div style="background:rgba(17,17,19,.88);border:1px solid #27272a;border-radius:14px;padding:16px"><div style="color:#a1a1aa;font-size:11px;text-transform:uppercase;letter-spacing:1px">Distribución emocional</div><div style="display:flex;align-items:end;gap:8px;height:38px;margin:8px 0"><div title="Positivo: '+pos+'" style="height:'+Math.max(6,Math.round(pos/max*100))+'%;flex:1;background:#22c55e;border-radius:5px 5px 2px 2px"></div><div title="Neutral: '+neu+'" style="height:'+Math.max(6,Math.round(neu/max*100))+'%;flex:1;background:#f59e0b;border-radius:5px 5px 2px 2px"></div><div title="Negativo: '+neg+'" style="height:'+Math.max(6,Math.round(neg/max*100))+'%;flex:1;background:#ef4444;border-radius:5px 5px 2px 2px"></div></div><span style="color:#a1a1aa;font-size:12px">Positivo '+pos+' · Neutral '+neu+' · Negativo '+neg+'</span></div><div style="background:rgba(17,17,19,.88);border:1px solid #27272a;border-radius:14px;padding:16px"><div style="color:#a1a1aa;font-size:11px;text-transform:uppercase;letter-spacing:1px">Oportunidades visibles</div><strong style="display:block;font-size:28px;color:#f47b20">'+total+'</strong><span style="color:#a1a1aa;font-size:12px">Leads calificados en el pipeline</span></div>'}
function setupFilters(){if(document.getElementById('lead-filters'))return;document.querySelector('#pipeline .stats').insertAdjacentHTML('beforebegin','<div id="lead-filters" style="display:flex;gap:8px;flex-wrap:wrap;margin:0 0 16px"><input id="lead-search" placeholder="Buscar por nombre, teléfono, rubro o interés" style="flex:1;min-width:240px;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px"><select id="sentiment-filter" style="background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px"><option value="">Todos los sentimientos</option><option value="positivo">Positivos</option><option value="neutral">Neutrales</option><option value="negativo">Negativos</option></select><button id="clear-filters" style="border:0;border-radius:8px;padding:10px 13px;background:#3f3f46;color:#fff;cursor:pointer">Limpiar</button></div>');var apply=function(){var q=(document.getElementById('lead-search').value||'').toLowerCase().trim(),sent=document.getElementById('sentiment-filter').value;document.querySelectorAll('.card[data-tel]').forEach(function(c){var l=leads.find(function(x){return x.telefono===c.dataset.tel}),hay=l&&[l.nombre,l.telefono,l.rubro,l.presupuesto,l.interes,l.resumen].join(' ').toLowerCase().indexOf(q)>=0,ok=!sent||l.sentiment_label===sent;c.style.display=hay&&ok?'':'none'});};document.getElementById('lead-search').addEventListener('input',apply);document.getElementById('sentiment-filter').addEventListener('change',apply);document.getElementById('clear-filters').onclick=function(){document.getElementById('lead-search').value='';document.getElementById('sentiment-filter').value='';apply()}}
function decorateFollowupCards(){document.querySelectorAll('.card[data-tel]').forEach(function(c){var l=leads.find(function(x){return x.telefono===c.dataset.tel});if(!l)return;var data=c.querySelector('.data'),actions=c.querySelector('.actions');if(data&&!data.querySelector('.followup-data'))data.insertAdjacentHTML('beforeend','<div class="muted followup-data" style="margin-top:8px"><strong>Nota:</strong> '+esc(l.nota||'Sin nota')+'<br><strong>Próxima:</strong> '+esc(l.proxima_accion||'Sin definir')+'</div>');if(actions&&!actions.querySelector('.edit-followup'))actions.insertAdjacentHTML('afterbegin','<button class="edit-followup" data-tel="'+esc(l.telefono)+'">Seguimiento</button>')})}
function decorateOpportunityCards(){document.querySelectorAll('.card[data-tel]').forEach(function(c){var l=leads.find(function(x){return x.telefono===c.dataset.tel});if(!l)return;var data=c.querySelector('.data'),actions=c.querySelector('.actions');if(data&&!data.querySelector('.opportunity-data'))data.insertAdjacentHTML('beforeend','<div class="muted opportunity-data" style="margin-top:8px"><strong>Valor:</strong> '+esc(l.valor_oportunidad||'Sin definir')+' · <strong>Origen:</strong> '+esc(l.origen||'WhatsApp')+'<br><strong>Fecha:</strong> '+esc(l.fecha_proxima_accion||'Sin definir')+'</div>');if(actions&&!actions.querySelector('.edit-opportunity'))actions.insertAdjacentHTML('afterbegin','<button class="edit-opportunity" data-tel="'+esc(l.telefono)+'">Datos comerciales</button>')})}
var loadWithInsights=load;load=async function(){await loadWithInsights();renderInsights();setupFilters();decorateFollowupCards();decorateOpportunityCards()};
function openFollowup(t){var l=leads.find(function(x){return x.telefono===t});if(!l)return;var old=document.getElementById('followup-dialog');if(old)old.remove();var box=document.createElement('div');box.id='followup-dialog';box.style='position:fixed;inset:0;background:#000b;z-index:20;display:flex;align-items:center;justify-content:center;padding:20px';box.innerHTML='<div style="width:min(560px,100%);background:#111113;border:1px solid #3f3f46;border-radius:16px;padding:22px;box-shadow:0 20px 60px #000"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h2 style="margin:0">Seguimiento comercial</h2><button id="cancel-followup" style="background:none;border:0;color:#a1a1aa;font-size:24px;cursor:pointer">×</button></div><label style="display:block;color:#a1a1aa;font-size:12px;margin:0 0 6px">Nota interna</label><textarea id="followup-note" rows="4" style="width:100%;box-sizing:border-box;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px;resize:vertical">'+esc(l.nota||'')+'</textarea><label style="display:block;color:#a1a1aa;font-size:12px;margin:14px 0 6px">Próxima acción</label><input id="followup-next" value="'+esc(l.proxima_accion||'')+'" placeholder="Ej: llamar el jueves por la tarde" style="width:100%;box-sizing:border-box;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px"><div style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px"><button id="cancel-followup-2" class="actions button" style="border:1px solid #3f3f46;border-radius:8px;padding:9px 13px;background:#27272a;color:#fff;cursor:pointer">Cancelar</button><button id="save-followup" style="border:0;border-radius:8px;padding:9px 13px;background:#f47b20;color:#09090b;font-weight:700;cursor:pointer">Guardar seguimiento</button></div></div>';document.body.appendChild(box);var close=function(){box.remove()};document.getElementById('cancel-followup').onclick=close;document.getElementById('cancel-followup-2').onclick=close;document.getElementById('save-followup').onclick=async function(){var r=await fetch('/leads/'+encodeURIComponent(t)+'/seguimiento',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nota:document.getElementById('followup-note').value,proxima_accion:document.getElementById('followup-next').value})});if(r.ok){close();load()}else alert('No se pudo guardar el seguimiento')}}
document.addEventListener('click',function(e){var b=e.target.closest('.edit-followup');if(b)openFollowup(b.dataset.tel)});
function openOpportunity(t){var l=leads.find(function(x){return x.telefono===t});if(!l)return;var old=document.getElementById('opportunity-dialog');if(old)old.remove();var box=document.createElement('div');box.id='opportunity-dialog';box.style='position:fixed;inset:0;background:#000b;z-index:20;display:flex;align-items:center;justify-content:center;padding:20px';box.innerHTML='<div style="width:min(560px,100%);background:#111113;border:1px solid #3f3f46;border-radius:16px;padding:22px"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px"><h2 style="margin:0">Datos comerciales</h2><button id="cancel-opportunity" style="background:none;border:0;color:#a1a1aa;font-size:24px;cursor:pointer">×</button></div><label style="display:block;color:#a1a1aa;font-size:12px;margin:0 0 6px">Valor estimado de oportunidad</label><input id="opportunity-value" value="'+esc(l.valor_oportunidad||'')+'" placeholder="Ej: USD 2.000" style="width:100%;box-sizing:border-box;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px"><label style="display:block;color:#a1a1aa;font-size:12px;margin:14px 0 6px">Origen</label><input id="opportunity-origin" value="'+esc(l.origen||'WhatsApp')+'" placeholder="Ej: WhatsApp, Meta Ads, formulario" style="width:100%;box-sizing:border-box;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px"><label style="display:block;color:#a1a1aa;font-size:12px;margin:14px 0 6px">Fecha de próxima acción</label><input id="opportunity-date" type="date" value="'+esc(l.fecha_proxima_accion||'')+'" style="width:100%;box-sizing:border-box;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px"><div style="display:flex;justify-content:flex-end;gap:8px;margin-top:18px"><button id="cancel-opportunity-2" style="border:1px solid #3f3f46;border-radius:8px;padding:9px 13px;background:#27272a;color:#fff;cursor:pointer">Cancelar</button><button id="save-opportunity" style="border:0;border-radius:8px;padding:9px 13px;background:#f47b20;color:#09090b;font-weight:700;cursor:pointer">Guardar datos</button></div></div>';document.body.appendChild(box);var close=function(){box.remove()};document.getElementById('cancel-opportunity').onclick=close;document.getElementById('cancel-opportunity-2').onclick=close;document.getElementById('save-opportunity').onclick=async function(){var r=await fetch('/leads/'+encodeURIComponent(t)+'/oportunidad',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({valor_oportunidad:document.getElementById('opportunity-value').value,origen:document.getElementById('opportunity-origin').value,fecha_proxima_accion:document.getElementById('opportunity-date').value})});if(r.ok){close();load()}else alert('No se pudieron guardar los datos comerciales')}}
document.addEventListener('click',function(e){var b=e.target.closest('.edit-opportunity');if(b)openOpportunity(b.dataset.tel)});
async function seedDemo(){var r=await fetch('/api/demo/seed',{method:'POST'});var d=await r.json();alert(d.mensaje+' ('+d.creados+' nuevos)');load()}
async function loadInbox(){var d=await (await fetch('/conversaciones')).json(),leadsMap={};leads.forEach(function(l){leadsMap[l.telefono]=l});var box=document.getElementById('inbox-list');if(!box)return;box.innerHTML=(d.conversaciones||[]).map(function(c){var l=leadsMap[c.telefono],nombre=l?(l.nombre||'Sin nombre'):'Contacto nuevo',estado=l?(stage(l)==='seguimiento'?'Calificado · seguimiento':stage(l)==='cerrado'?'Cerrado':'Descartado'):'En conversación';return '<article class="card'+(l&&l.no_leido?' unread':'')+'"><div class="cardtop"><div><div class="name">'+(l&&l.no_leido?'<span class="unread-mark" title="No leído"></span>':'')+esc(nombre)+'</div><div class="phone">+'+esc(c.telefono.replace('@s.whatsapp.net','').replace('@c.us',''))+'</div></div><span class="pill">'+estado+'</span></div><div class="data"><div><strong>Mensajes:</strong> '+c.mensajes+'</div><div class="muted">Último contacto: '+new Date(c.ultimo_mensaje).toLocaleString('es-AR')+'</div></div><div class="actions"><button class="open-inbox-chat" data-tel="'+esc(c.telefono)+'">Ver conversación</button></div></article>'}).join('')||'<div class="empty">Todavía no hay conversaciones.</div>'}
document.querySelector('.top').insertAdjacentHTML('beforeend','<div class="header-actions" style="position:relative;margin-right:8px"><button id="actions-menu-button" class="connect" style="width:auto;margin:0">Acciones ▾</button><div id="actions-menu" style="display:none;position:absolute;right:0;top:46px;min-width:210px;background:#111113;border:1px solid #3f3f46;border-radius:10px;padding:6px;box-shadow:0 16px 35px #0008;z-index:12"><button id="seed-demo-action" style="display:block;width:100%;text-align:left;background:none;border:0;color:#fff;padding:10px;border-radius:7px;cursor:pointer">Cargar datos demo</button><a href="/export/leads.csv" style="display:block;color:#fff;text-decoration:none;padding:10px;border-radius:7px">Exportar leads</a><a href="/export/conversaciones.csv" style="display:block;color:#fff;text-decoration:none;padding:10px;border-radius:7px">Exportar conversaciones</a></div></div>');document.getElementById('actions-menu-button').onclick=function(){var m=document.getElementById('actions-menu');m.style.display=m.style.display==='none'?'block':'none'};document.getElementById('seed-demo-action').onclick=function(){document.getElementById('actions-menu').style.display='none';seedDemo()};document.addEventListener('click',function(e){if(!e.target.closest('.header-actions'))document.getElementById('actions-menu').style.display='none'});
document.querySelector('.tabs').insertAdjacentHTML('beforeend','<button class="tab" data-tab="inbox">Bandeja</button>');document.querySelector('main').insertAdjacentHTML('beforeend','<section id="inbox" class="panel"><div id="inbox-list" class="pipeline" style="grid-template-columns:repeat(3,1fr)"></div><div class="note">Acá aparecen todos los contactos que hablaron con Max, incluso los que todavía no completaron la calificación.</div></section>');document.querySelectorAll('.tab').forEach(function(b){b.onclick=function(){document.querySelectorAll('.tab,.panel').forEach(function(x){x.classList.remove('active')});b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active');if(b.dataset.tab==='canales')loadChannels();if(b.dataset.tab==='inbox')loadInbox()}});load();setInterval(load,30000);
</script></body></html>""")
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    if BRAND_LOGO_URL:
        # Solo se reemplaza el "MC" de texto por una imagen si el cliente
        # configuró un logo (BRAND_LOGO_URL). Sin eso, queda el mark de texto
        # con las iniciales de BRAND_SHORT — generado más abajo por _marca().
        response.body = response.body.replace(
            '<header class="top"><div class="brand"><div class="mark">MC</div><div>MC Growth <small>Growth OS · Lead intelligence</small></div></div><div class="live">● Max operativo</div></header>'.encode("utf-8"),
            f'<header class="top" style="height:72px;padding:0 32px"><div class="brand" style="gap:0"><img src="{BRAND_LOGO_URL}" alt="{BRAND_COMPANY}" style="width:154px;height:auto;display:block;filter:drop-shadow(0 0 12px rgba(244,123,32,.28))"></div><div class="live">● Max operativo</div></header>'.encode("utf-8"),
            1,
        )
        response.body = response.body.replace(
            b'<div class="mark">MC</div>',
            f'<div class="mark" aria-label="{BRAND_COMPANY}"><img src="{BRAND_LOGO_URL}" alt="{BRAND_COMPANY}" style="width:24px;height:24px;display:block;object-fit:contain"></div>'.encode("utf-8"),
            1,
        )
    sales_script = '''<script>
    (function(){
      var oldPipeline=document.querySelector('#pipeline .pipeline');
      if(!oldPipeline)return;
      oldPipeline.style.display='none';
      oldPipeline.insertAdjacentHTML('beforebegin','<h2 style="margin:24px 0 12px">Pipeline comercial</h2><div id="sales-pipeline" style="display:grid;grid-template-columns:repeat(6,minmax(210px,1fr));gap:12px;overflow-x:auto;padding-bottom:8px"></div>');
      var defaultStages=[['nuevo','Nuevo'],['contactado','Contactado'],['propuesta','Propuesta'],['negociacion','Negociación'],['ganado','Ganado'],['perdido','Perdido']];
      var normalize=function(l){if(l.cerrado)return 'ganado';if(l.descartado)return 'perdido';if(l.etapa==='seguimiento')return 'contactado';if(l.etapa==='cerrado')return 'ganado';if(l.etapa==='descartado')return 'perdido';return l.etapa||'contactado'};
      function renderSales(){var box=document.getElementById('sales-pipeline');if(!box)return;var stages=window.crmStages||defaultStages;box.innerHTML=stages.map(function(s){return '<section class="stage" data-sales-stage="'+s[0]+'" style="min-height:300px"><h3>'+s[1]+' <span id="sales-count-'+s[0]+'">0</span></h3><div id="sales-col-'+s[0]+'"></div></section>'}).join('');stages.forEach(function(s){var key=s[0],items=leads.filter(function(l){return normalize(l)===key}),col=document.getElementById('sales-col-'+key);document.getElementById('sales-count-'+key).textContent=items.length;col.innerHTML=items.map(function(l){return '<article class="card sales-card'+(l.no_leido?' unread':'')+'" draggable="true" data-tel="'+esc(l.telefono)+'"><div class="cardtop"><div><div class="name">'+(l.no_leido?'<span class="unread-mark" title="No leído"></span>':'')+esc(l.nombre||'Sin nombre')+'</div><div class="phone">+'+esc(l.telefono.replace('@s.whatsapp.net','').replace('@c.us',''))+'</div></div><span class="pill '+esc(l.sentiment_label||'neutral')+'">'+(l.sentiment_score||50)+'/100</span></div><div class="cal-row">'+(l.calificado?'<span class="pill cal-yes">✓ Calificado</span>':'<span class="pill cal-no">Sin calificar</span>')+'</div><div class="data"><div><strong>Rubro:</strong> '+esc(l.rubro)+'</div><div><strong>Interés:</strong> '+esc(l.interes)+'</div><div><strong>Próxima:</strong> '+esc(l.proxima_accion||'Sin definir')+'</div></div><div class="actions"><button class="sales-open" data-tel="'+esc(l.telefono)+'">Chat</button><button class="sales-followup" data-tel="'+esc(l.telefono)+'">Seguimiento</button><button class="sales-opportunity" data-tel="'+esc(l.telefono)+'">Datos</button><button class="sales-qualify" data-tel="'+esc(l.telefono)+'" data-calificado="'+(l.calificado?'1':'0')+'">'+(l.calificado?'Quitar calificación':'Marcar calificado')+'</button><button class="sales-delete" data-tel="'+esc(l.telefono)+'" style="background:#7f1d1d">Eliminar</button></div></article>'}).join('')||'<div class="empty">Sin oportunidades</div>'});document.querySelectorAll('.sales-card').forEach(function(c){c.addEventListener('dragstart',function(e){e.dataTransfer.setData('sales-tel',c.dataset.tel)})});document.querySelectorAll('[data-sales-stage]').forEach(function(c){c.ondragover=function(e){e.preventDefault()};c.ondrop=async function(e){var tel=e.dataTransfer.getData('sales-tel');if(!tel)return;var r=await fetch('/leads/'+encodeURIComponent(tel)+'/estado',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({estado:c.dataset.salesStage})});if(r.ok){var d=await (await fetch('/leads')).json();leads=d.leads||[];renderSales()}}})}
      document.addEventListener('click',function(e){var b=e.target.closest('.sales-open,.sales-followup,.sales-opportunity');if(!b)return;var l=leads.find(function(x){return x.telefono===b.dataset.tel});if(!l)return;if(b.classList.contains('sales-open'))openChat(encodeURIComponent(b.dataset.tel),l.nombre||b.dataset.tel);if(b.classList.contains('sales-followup'))openFollowup(b.dataset.tel);if(b.classList.contains('sales-opportunity'))openOpportunity(b.dataset.tel)});
      document.addEventListener('click',async function(e){var b=e.target.closest('.sales-delete');if(!b)return;if(!confirm('Eliminar definitivamente este lead y toda su conversación? Esta acción no se puede deshacer.'))return;var r=await fetch('/leads/'+encodeURIComponent(b.dataset.tel),{method:'DELETE'});if(r.ok){var d=await (await fetch('/leads')).json();leads=d.leads||[];renderSales()}else alert('No se pudo eliminar el lead')});
      document.addEventListener('click',async function(e){var b=e.target.closest('.sales-qualify');if(!b)return;var nuevoValor=b.dataset.calificado!=='1';var r=await fetch('/leads/'+encodeURIComponent(b.dataset.tel)+'/calificado',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({calificado:nuevoValor})});if(r.ok){var d=await (await fetch('/leads')).json();leads=d.leads||[];renderSales();if(window.renderAnalytics)window.renderAnalytics()}else alert('No se pudo actualizar la calificación')});
      var previousLoad=load;load=async function(){await previousLoad();renderSales()};previousLoad().then(renderSales);setInterval(async function(){var d=await (await fetch('/leads')).json();leads=d.leads||[];renderSales()},30000);
      window.renderSales=renderSales;
    })();
    </script>'''
    response.body = response.body.replace(b'</body></html>', sales_script.encode('utf-8') + b'</body></html>', 1)
    workspace_script = '''<style>
    .crm-side{position:fixed;left:0;top:0;bottom:0;width:236px;background:rgba(9,9,11,.94);border-right:1px solid #27272a;padding:92px 14px 18px;z-index:3;backdrop-filter:blur(18px)}
    .unread-dot{display:inline-block;min-width:18px;height:18px;line-height:18px;text-align:center;border-radius:99px;background:#ef4444;color:#fff;font-size:10px;font-weight:800;margin-left:auto;padding:0 5px}
    .card.unread{border-color:#ef4444}
    .card .unread-mark{display:inline-block;width:9px;height:9px;border-radius:50%;background:#ef4444;margin-right:6px;vertical-align:middle}
    .cal-row{margin:6px 0}.cal-yes{background:#166534!important;color:#dcfce7!important}.cal-no{background:#3f3f46!important;color:#a1a1aa!important}
    .sales-qualify{background:#1e3a5f!important}
    .crm-side .side-label{color:#71717a;font-size:10px;text-transform:uppercase;letter-spacing:1.4px;padding:0 10px;margin:18px 0 8px}
    .crm-side button{width:100%;display:flex;align-items:center;gap:10px;background:transparent;border:0;color:#a1a1aa;text-align:left;border-radius:10px;padding:11px 12px;margin:3px 0;font:inherit;cursor:pointer}
    .crm-side button:hover,.crm-side button.active{background:#27272a;color:#fff}.crm-side button.active{box-shadow:inset 3px 0 #f47b20}
    .crm-side .side-icon{width:22px;text-align:center;color:#f47b20;font-size:16px}.crm-side small{display:block;color:#71717a;margin:18px 10px 0;line-height:1.45}.header-actions .connect{font-size:12px;padding:8px 11px}.header-actions .connect:before{content:'⋯';display:none}
    .crm-content-shift{margin-left:236px!important;max-width:none!important}.crm-top-shift{margin-left:236px}
    .crm-overview{display:none}.crm-overview.active{display:block}.crm-overview-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:22px 0}.crm-kpi{background:rgba(17,17,19,.88);border:1px solid #27272a;border-radius:14px;padding:17px}.crm-kpi b{font-size:28px;display:block}.crm-kpi span,.crm-chart-label{color:#a1a1aa;font-size:12px}.crm-chart-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:14px}.crm-chart{background:rgba(17,17,19,.88);border:1px solid #27272a;border-radius:14px;padding:18px}.crm-chart h3{margin:0 0 16px;font-size:15px}.crm-bars{display:flex;align-items:end;gap:10px;height:155px;border-bottom:1px solid #3f3f46;padding:0 8px}.crm-bar-col{flex:1;height:100%;display:flex;flex-direction:column;justify-content:end;align-items:center;gap:7px}.crm-bar{width:100%;max-width:44px;min-height:4px;border-radius:7px 7px 0 0;background:linear-gradient(180deg,#ff9a4d,#f47b20)}.crm-bar-value{font-size:11px;color:#f4f4f5}.crm-bar-name{font-size:10px;color:#a1a1aa;white-space:nowrap}.crm-donut{display:grid;grid-template-columns:150px 1fr;gap:18px;align-items:center}.crm-ring{width:142px;height:142px;border-radius:50%;display:grid;place-items:center;background:conic-gradient(#22c55e 0 35%,#f59e0b 35% 70%,#ef4444 70% 100%);position:relative}.crm-ring:after{content:'';width:86px;height:86px;border-radius:50%;background:#111113;position:absolute}.crm-ring strong{position:relative;z-index:1;font-size:24px}.crm-legend div{margin:8px 0;font-size:12px;color:#d4d4d8}.crm-dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px}.crm-report-panel{display:none}.crm-report-panel.active{display:block}.crm-report-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:14px;margin-top:20px}.crm-stage-row{display:grid;grid-template-columns:120px 1fr 42px;align-items:center;gap:10px;margin:12px 0;font-size:12px}.crm-stage-track{height:9px;background:#27272a;border-radius:99px;overflow:hidden}.crm-stage-fill{height:100%;background:linear-gradient(90deg,#f47b20,#ffb067);border-radius:99px}.crm-export-row{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0}.crm-export-row a{display:inline-block;text-decoration:none;background:#27272a;color:#fff;border:1px solid #3f3f46;padding:9px 12px;border-radius:8px;font-size:12px}.crm-export-row a:hover{border-color:#f47b20}@media(max-width:900px){.crm-side{width:64px;padding-left:8px;padding-right:8px}.crm-side button{justify-content:center;padding:11px 8px}.crm-side button span:not(.side-icon),.crm-side .side-label,.crm-side small{display:none}.crm-content-shift,.crm-top-shift{margin-left:64px!important}.crm-overview-grid{grid-template-columns:repeat(2,1fr)}.crm-chart-grid,.crm-report-grid{grid-template-columns:1fr}.crm-donut{grid-template-columns:1fr}}
    .crm-period{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:20px 0 4px}.crm-period select,.crm-period input{background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:9px}.crm-insight{margin:14px 0 18px;padding:14px 16px;border:1px solid rgba(244,123,32,.35);border-radius:12px;background:rgba(124,63,18,.18);color:#fed7aa;line-height:1.5}.crm-manual-dialog{position:fixed;inset:0;background:#000b;z-index:25;display:flex;align-items:center;justify-content:center;padding:20px}.crm-manual-card{width:min(720px,100%);max-height:90vh;overflow:auto;background:#111113;border:1px solid #3f3f46;border-radius:16px;padding:22px}.crm-form-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}.crm-form-grid label{display:block;color:#a1a1aa;font-size:12px}.crm-form-grid input,.crm-form-grid textarea,.crm-form-grid select{width:100%;box-sizing:border-box;margin-top:6px;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px}.crm-form-grid textarea{min-height:78px;resize:vertical}.crm-form-wide{grid-column:1/-1}.crm-form-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.human-reply{display:flex;gap:8px;margin-top:14px;border-top:1px solid #27272a;padding-top:14px}.human-reply textarea{flex:1;min-height:44px;resize:vertical;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:10px;font:inherit}.human-reply .connect{width:auto;align-self:flex-end}@media(max-width:520px){.top{padding:0 10px!important}.top .brand img{width:118px!important}.top .live{font-size:10px;padding:6px 8px}.header-actions .connect{font-size:0;padding:8px 10px}.header-actions .connect:before{display:block;font-size:18px;line-height:12px}.crm-overview-grid{grid-template-columns:1fr}.crm-form-grid{grid-template-columns:1fr}.crm-form-wide{grid-column:auto}.crm-chart{padding:14px}.crm-bars{gap:4px}.crm-bar-name{font-size:8px}.human-reply{flex-direction:column}.human-reply .connect{width:100%}.crm-content-shift{padding-left:10px!important;padding-right:10px!important}}
    #sales-pipeline{scrollbar-color:#f47b20 #18181b}@media(max-width:900px){#sales-pipeline{grid-template-columns:repeat(2,minmax(0,1fr))!important;overflow-x:visible!important}.sales-card{min-width:0}.sales-card .actions button{flex:1;min-width:80px}.crm-chart-grid{gap:10px}}
    @media(max-width:560px){#sales-pipeline{grid-template-columns:1fr!important;gap:10px!important}.sales-card{padding:12px}.sales-card .data{font-size:11px}.sales-card .actions{display:grid;grid-template-columns:repeat(2,1fr)}.sales-card .actions button{min-width:0;width:100%;font-size:11px}.crm-side{width:56px}.crm-content-shift,.crm-top-shift{margin-left:56px!important}.crm-content-shift{padding-left:10px!important;padding-right:10px!important}.intro h1{font-size:22px}.crm-kpi b{font-size:24px}.crm-donut{justify-items:center}.crm-ring{width:120px;height:120px}.crm-ring:after{width:72px;height:72px}.crm-report-grid{gap:10px}.crm-stage-row{grid-template-columns:88px 1fr 30px;gap:7px;font-size:11px}}
    </style><script>
    (function(){
      var main=document.querySelector('main.wrap'), top=document.querySelector('.top');
      if(!main||document.getElementById('crm-side'))return;
      main.classList.add('crm-content-shift'); top.classList.add('crm-top-shift');
      var side=document.createElement('aside');side.id='crm-side';side.className='crm-side';side.innerHTML='<div class="side-label">Workspace</div><button class="active" data-view="overview"><span class="side-icon">◉</span><span>Resumen</span></button><button data-view="pipeline"><span class="side-icon">▦</span><span>Pipeline</span><span id="unread-pipeline" class="unread-dot" style="display:none"></span></button><button data-view="inbox"><span class="side-icon">☷</span><span>Conversaciones</span><span id="unread-inbox" class="unread-dot" style="display:none"></span></button><button data-view="manual"><span class="side-icon">＋</span><span>Nuevo lead</span></button><div class="side-label">Análisis</div><button data-view="reportes"><span class="side-icon">↗</span><span>Reportes</span></button><button data-view="canales"><span class="side-icon">◌</span><span>Canales</span></button><div class="side-label">Administración</div><button data-view="settings"><span class="side-icon">⚙</span><span>Personalizar</span></button><small>MC Growth OS<br>Lead intelligence</small>';
      document.body.insertBefore(side,document.body.firstChild);document.querySelector('.tabs').style.display='none';document.getElementById('chat').insertAdjacentHTML('afterend','<div class="human-reply"><textarea id="human-reply" placeholder="Responder como comercial..."></textarea><button id="send-human-reply" class="connect">Enviar como comercial</button></div>');document.getElementById('send-human-reply').addEventListener('click',sendHumanReply);
      main.insertAdjacentHTML('afterbegin','<section id="overview" class="crm-overview active"><div class="intro"><h1>Resumen ejecutivo</h1><p>Una lectura rápida de la operación comercial de Max.</p></div><div class="crm-period"><strong>Período</strong><select id="analytics-period"><option value="week">Esta semana</option><option value="month" selected>Este mes</option><option value="custom">Personalizado</option></select><input id="analytics-from" type="date" style="display:none"><input id="analytics-to" type="date" style="display:none"></div><div id="crm-insight" class="crm-insight">Analizando la actividad comercial…</div><div class="crm-overview-grid"><div class="crm-kpi"><b id="ov-total">0</b><span>Oportunidades</span></div><div class="crm-kpi"><b id="ov-active" style="color:#fbbf24">0</b><span>En proceso</span></div><div class="crm-kpi"><b id="ov-won" style="color:#86efac">0</b><span>Ganadas</span></div><div class="crm-kpi"><b id="ov-rate" style="color:#f47b20">0%</b><span>Tasa de cierre</span></div><div class="crm-kpi"><b id="ov-qualified" style="color:#60a5fa">0%</b><span>Tasa de calificación</span></div></div><div class="crm-chart-grid"><div class="crm-chart"><h3>Leads por etapa</h3><div id="ov-stage-bars" class="crm-bars"></div></div><div class="crm-chart"><h3>Sentimiento de los leads</h3><div class="crm-donut"><div id="ov-ring" class="crm-ring"><strong id="ov-score">0</strong></div><div id="ov-legend" class="crm-legend"></div></div></div></div></section>');
      main.insertAdjacentHTML('beforeend','<section id="reportes" class="crm-report-panel"><div class="intro"><h1>Reportes comerciales</h1><p>Distribución de oportunidades y señales para decidir dónde poner foco.</p></div><div class="crm-export-row"><a href="/export/leads.csv">Exportar leads</a><a href="/export/conversaciones.csv">Exportar conversaciones</a></div><div class="crm-report-grid"><div class="crm-chart"><h3>Embudo comercial</h3><div id="report-funnel"></div></div><div class="crm-chart"><h3>Origen de oportunidades</h3><div id="report-origin"></div></div></div></section>');
      main.insertAdjacentHTML('beforeend','<section id="settings" class="crm-report-panel"><div class="intro"><h1>Personalizar workspace</h1><p>Configurá el CRM desde acá. No hace falta editar código ni escribir comandos.</p></div><div class="crm-report-grid"><div class="crm-chart"><h3>Etapas del pipeline</h3><p class="crm-chart-label">Renombrá columnas, cambiá su color o agregá nuevas etapas.</p><div id="settings-stages"></div><button id="add-stage" class="connect" style="width:auto;margin-top:10px">+ Agregar etapa</button></div><div class="crm-chart"><h3>Campos comerciales</h3><p class="crm-chart-label">Elegí qué información querés que el equipo complete en cada oportunidad.</p><div id="settings-fields"></div><button id="add-field" class="connect" style="width:auto;margin-top:10px">+ Agregar campo</button><div style="margin-top:20px"><button id="save-settings" class="connect">Guardar personalización</button></div></div></div></section>');
      function normalized(l){if(l.cerrado)return 'ganado';if(l.descartado)return 'perdido';if(l.etapa==='seguimiento')return 'contactado';if(l.etapa==='cerrado')return 'ganado';if(l.etapa==='descartado')return 'perdido';return l.etapa||'contactado'}
      function esc2(s){return esc(s)}
      function getAnalyticsRange(){var all=typeof leads!=='undefined'?leads:[],mode=document.getElementById('analytics-period').value,now=new Date(),from=new Date(now),to=new Date(now);if(mode==='week'){from.setDate(now.getDate()-6);from.setHours(0,0,0,0)}else if(mode==='month'){from.setDate(1);from.setHours(0,0,0,0)}else{from=new Date(document.getElementById('analytics-from').value||now.toISOString().slice(0,10));from.setHours(0,0,0,0);to=new Date(document.getElementById('analytics-to').value||now.toISOString().slice(0,10));to.setHours(23,59,59,999)}if(mode!=='custom')to=now;var days=Math.max(1,Math.ceil((to-from)/86400000)+1),previousFrom=new Date(from.getTime()-days*86400000),previousTo=new Date(from.getTime()-1),inside=function(l,a,b){var d=new Date(l.timestamp);return !isNaN(d)&&d>=a&&d<=b};return {current:all.filter(function(l){return inside(l,from,to)}),previous:all.filter(function(l){return inside(l,previousFrom,previousTo)}),days:days}}
      function formatPeriodInsight(current,previous){var delta=function(a,b){return b?Math.round((a-b)/b*100):a?100:0},msg=[],c=current.length,p=previous.length,d=delta(c,p),cw=current.filter(function(l){return normalized(l)==='ganado'}).length,pw=previous.filter(function(l){return normalized(l)==='ganado'}).length;if(d)msg.push('Entraron '+Math.abs(d)+'% '+(d>0?'más':'menos')+' oportunidades que en el período anterior.');if(cw!==pw)msg.push('Se ganaron '+cw+' oportunidades, '+(cw>pw?'por encima':'por debajo')+' del período anterior ('+pw+').');var avg=c?Math.round(current.reduce(function(a,l){return a+(Number(l.sentiment_score)||50)},0)/c):0;if(avg)msg.push('El sentimiento promedio fue de '+avg+'/100.');return msg.join(' ')||'Todavía no hay suficiente actividad para comparar períodos.'}
      function renderAnalytics(){var range=getAnalyticsRange(),list=range.current,keys=window.crmStages||[['nuevo','Nuevo'],['contactado','Contactado'],['propuesta','Propuesta'],['negociacion','Negociación'],['ganado','Ganado'],['perdido','Perdido']],counts=keys.map(function(x){return list.filter(function(l){return normalized(l)===x[0]}).length}),total=list.length||0,won=list.filter(function(l){return normalized(l)==='ganado'}).length,lost=list.filter(function(l){return normalized(l)==='perdido'}).length,active=total-won-lost;document.getElementById('crm-insight').textContent=formatPeriodInsight(list,range.previous);document.getElementById('ov-total').textContent=total;document.getElementById('ov-active').textContent=active;document.getElementById('ov-won').textContent=won;document.getElementById('ov-rate').textContent=(total?Math.round(won/total*100):0)+'%';var calificados=list.filter(function(l){return l.calificado}).length;document.getElementById('ov-qualified').textContent=(total?Math.round(calificados/total*100):0)+'%';var max=Math.max.apply(null,counts.concat([1]));document.getElementById('ov-stage-bars').innerHTML=keys.map(function(x,i){return '<div class="crm-bar-col"><span class="crm-bar-value">'+counts[i]+'</span><div class="crm-bar" style="height:'+Math.max(4,Math.round(counts[i]/max*112))+'px"></div><span class="crm-bar-name">'+x[1]+'</span></div>'}).join('');var pos=list.filter(function(l){return l.sentiment_label==='positivo'}).length,neu=list.filter(function(l){return l.sentiment_label==='neutral'||!l.sentiment_label}).length,neg=list.filter(function(l){return l.sentiment_label==='negativo'}).length,sum=pos+neu+neg||1,avg=Math.round(list.reduce(function(a,l){return a+(Number(l.sentiment_score)||50)},0)/sum);document.getElementById('ov-score').textContent=avg;document.getElementById('ov-ring').style.background='conic-gradient(#22c55e 0 '+(pos/sum*100)+'%,#f59e0b '+(pos/sum*100)+'% '+((pos+neu)/sum*100)+'%,#ef4444 '+((pos+neu)/sum*100)+'% 100%)';document.getElementById('ov-legend').innerHTML='<div><i class="crm-dot" style="background:#22c55e"></i>Positivo: '+pos+'</div><div><i class="crm-dot" style="background:#f59e0b"></i>Neutral: '+neu+'</div><div><i class="crm-dot" style="background:#ef4444"></i>Negativo: '+neg+'</div>';document.getElementById('report-funnel').innerHTML=keys.map(function(x,i){return '<div class="crm-stage-row"><span>'+x[1]+'</span><div class="crm-stage-track"><div class="crm-stage-fill" style="width:'+(max?Math.max(counts[i]?4:0,counts[i]/max*100):0)+'%"></div></div><strong>'+counts[i]+'</strong></div>'}).join('');var origins={};list.forEach(function(l){var o=l.origen||'WhatsApp';origins[o]=(origins[o]||0)+1});var originMax=Math.max.apply(null,Object.keys(origins).map(function(k){return origins[k]}).concat([1]));document.getElementById('report-origin').innerHTML=Object.keys(origins).map(function(o){return '<div class="crm-stage-row"><span>'+esc2(o)+'</span><div class="crm-stage-track"><div class="crm-stage-fill" style="width:'+(origins[o]/originMax*100)+'%"></div></div><strong>'+origins[o]+'</strong></div>'}).join('')||'<div class="empty">Sin datos de origen.</div>'}
      var settings={};
      function inputStyle(){return 'width:100%;box-sizing:border-box;background:#18181b;color:#f4f4f5;border:1px solid #3f3f46;border-radius:8px;padding:9px'}
      function renderSettings(){var stages=(settings.pipeline&&settings.pipeline.etapas)||[],fields=(settings.pipeline&&settings.pipeline.campos)||[];document.getElementById('settings-stages').innerHTML=stages.map(function(s,i){return '<div class="settings-stage" style="display:grid;grid-template-columns:1fr 1.5fr 42px 28px;gap:7px;margin:10px 0;align-items:center"><input data-stage-key value="'+esc2(s.key)+'" readonly style="'+inputStyle()+';opacity:.65"><input data-stage-name value="'+esc2(s.nombre)+'" style="'+inputStyle()+'"><input data-stage-color type="color" value="'+esc2(s.color||'#f47b20')+'" style="width:38px;height:36px;background:#18181b;border:1px solid #3f3f46;border-radius:8px"><button data-remove-stage="'+i+'" style="background:#27272a;color:#fca5a5;border:0;border-radius:8px;height:36px;cursor:pointer">×</button></div>'}).join('')||'<div class="empty">Todavía no hay etapas.</div>';document.getElementById('settings-fields').innerHTML=fields.map(function(f,i){return '<div class="settings-field" style="display:flex;gap:7px;margin:10px 0"><input data-field-name value="'+esc2(f)+'" style="'+inputStyle()+'"><button data-remove-field="'+i+'" style="background:#27272a;color:#fca5a5;border:0;border-radius:8px;padding:0 13px;cursor:pointer">×</button></div>'}).join('')||'<div class="empty">Agregá el primer campo.</div>'}
      async function loadSettings(){settings=await (await fetch('/api/settings',{cache:'no-store'})).json();renderSettings()}
      function openLeadName(t){var l=leads.find(function(x){return x.telefono===t})||{},old=document.getElementById('name-dialog');if(old)old.remove();var box=document.createElement('div');box.id='name-dialog';box.className='crm-manual-dialog';box.innerHTML='<div class="crm-manual-card" style="max-width:420px"><div class="modalhead"><h2 style="margin:0">Nombre del contacto</h2><button id="close-name" class="close">×</button></div><label style="display:block;color:#a1a1aa;font-size:12px;margin:18px 0 6px">Nombre</label><input id="lead-name-input" value="'+esc2(l.nombre==='No indicó'?'':l.nombre||'')+'" placeholder="Ej: Juan García" style="'+inputStyle()+'"><div class="crm-form-actions"><button id="cancel-name" class="actions button">Cancelar</button><button id="save-name" class="connect" style="width:auto">Guardar nombre</button></div></div>';document.body.appendChild(box);var close=function(){box.remove()};document.getElementById('close-name').onclick=close;document.getElementById('cancel-name').onclick=close;document.getElementById('save-name').onclick=async function(){var r=await fetch('/leads/'+encodeURIComponent(t)+'/nombre',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({nombre:document.getElementById('lead-name-input').value})});if(r.ok){close();load()}else alert('No se pudo guardar el nombre')}}
      function decorateBotControls(){document.querySelectorAll('.sales-card[data-tel]').forEach(function(c){var l=leads.find(function(x){return x.telefono===c.dataset.tel}),a=c.querySelector('.actions');if(!l||!a||a.querySelector('.crm-toggle'))return;a.insertAdjacentHTML('beforeend','<button class="crm-toggle '+(l.bot_activo===false?'resume-max':'takeover')+'" data-tel="'+esc2(l.telefono)+'">'+(l.bot_activo===false?'Prender Max':'Apagar Max')+'</button>');if(l.nombre==='No indicó'&&!a.querySelector('.edit-name'))a.insertAdjacentHTML('beforeend','<button class="edit-name" data-tel="'+esc2(l.telefono)+'">Agregar nombre</button>')});document.querySelectorAll('#inbox .card').forEach(function(c){var b=c.querySelector('.open-inbox-chat'),a=c.querySelector('.actions');if(!b||!a||a.querySelector('.crm-toggle'))return;var t=b.dataset.tel,l=leads.find(function(x){return x.telefono===t})||{};a.insertAdjacentHTML('beforeend','<button class="crm-toggle '+(l.bot_activo===false?'resume-max':'takeover')+'" data-tel="'+esc2(t)+'">'+(l.bot_activo===false?'Prender Max':'Apagar Max')+'</button>');if(l.nombre==='No indicó')a.insertAdjacentHTML('beforeend','<button class="edit-name" data-tel="'+esc2(t)+'">Agregar nombre</button>')})}
      function openManualLead(){var old=document.getElementById('manual-lead-dialog');if(old)old.remove();var stages=(settings.pipeline&&settings.pipeline.etapas)||[];var box=document.createElement('div');box.id='manual-lead-dialog';box.className='crm-manual-dialog';box.innerHTML='<div class="crm-manual-card"><div class="modalhead"><div><h2 style="margin:0 0 4px">Agregar nuevo lead</h2><span class="muted">Cargalo manualmente aunque todavía no haya hablado con Max.</span></div><button id="close-manual-lead" class="close">×</button></div><div class="crm-form-grid" style="margin-top:18px"><label>Nombre<input id="manual-name" placeholder="Nombre y apellido"></label><label>Teléfono<input id="manual-phone" placeholder="54911..." required></label><label>Rubro<input id="manual-rubro" placeholder="Ej: Desarrolladora inmobiliaria"></label><label>Presupuesto<input id="manual-budget" placeholder="Ej: USD 1.000/mes"></label><label class="crm-form-wide">Interés concreto<textarea id="manual-interest" placeholder="Qué necesita o qué quiere resolver"></textarea></label><label>Origen<input id="manual-origin" value="Carga manual" placeholder="WhatsApp, Meta Ads, referido..."></label><label>Etapa<select id="manual-stage">'+stages.map(function(s){return '<option value="'+esc2(s.key)+'">'+esc2(s.nombre)+'</option>'}).join('')+'</select></label><label>Valor oportunidad<input id="manual-value" placeholder="Ej: USD 2.000"></label><label>Próxima acción<input id="manual-next" type="date"></label><label class="crm-form-wide">Resumen interno<textarea id="manual-summary" placeholder="Contexto breve para el equipo comercial"></textarea></label></div><div class="crm-form-actions"><button id="cancel-manual" class="actions button">Cancelar</button><button id="save-manual" class="connect" style="width:auto">Guardar lead</button></div></div>';document.body.appendChild(box);var close=function(){box.remove()};document.getElementById('close-manual-lead').onclick=close;document.getElementById('cancel-manual').onclick=close;document.getElementById('save-manual').onclick=async function(){var phone=document.getElementById('manual-phone').value.trim();if(!phone){alert('Ingresá un teléfono');return}var payload={telefono:phone,nombre:document.getElementById('manual-name').value,rubro:document.getElementById('manual-rubro').value,presupuesto:document.getElementById('manual-budget').value,interes:document.getElementById('manual-interest').value,origen:document.getElementById('manual-origin').value,etapa:document.getElementById('manual-stage').value,valor_oportunidad:document.getElementById('manual-value').value,fecha_proxima_accion:document.getElementById('manual-next').value,resumen:document.getElementById('manual-summary').value};var r=await fetch('/leads/manual',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(r.ok){close();await load();activate('pipeline')}else{var d=await r.json();alert(d.detail||'No se pudo agregar el lead')}}}
      function activate(view){if(view==='manual'){openManualLead();return}document.querySelectorAll('.crm-side button').forEach(function(b){b.classList.toggle('active',b.dataset.view===view)});document.querySelectorAll('.panel,.crm-overview,.crm-report-panel').forEach(function(x){x.classList.remove('active')});var target=document.getElementById(view==='reportes'?'reportes':view);if(target)target.classList.add('active');if(view==='canales')loadChannels();if(view==='inbox'){loadInbox();setTimeout(decorateBotControls,250)}if(view==='settings')loadSettings();if(view==='overview'||view==='reportes')renderAnalytics();window.scrollTo({top:0,behavior:'smooth'})}
      side.querySelectorAll('button').forEach(function(b){b.addEventListener('click',function(){activate(b.dataset.view)})});
      document.getElementById('analytics-period').addEventListener('change',function(){var custom=this.value==='custom';document.getElementById('analytics-from').style.display=custom?'inline-block':'none';document.getElementById('analytics-to').style.display=custom?'inline-block':'none';renderAnalytics()});document.getElementById('analytics-from').addEventListener('change',renderAnalytics);document.getElementById('analytics-to').addEventListener('change',renderAnalytics);
      document.addEventListener('click',function(e){var addStage=e.target.closest('#add-stage'),addField=e.target.closest('#add-field'),removeStage=e.target.closest('[data-remove-stage]'),removeField=e.target.closest('[data-remove-field]'),editName=e.target.closest('.edit-name');if(editName){openLeadName(editName.dataset.tel);return}if(addStage){var key='etapa_'+Date.now().toString(36);settings.pipeline.etapas.push({key:key,nombre:'Nueva etapa',color:'#f47b20',activa:true});renderSettings()}if(addField){settings.pipeline.campos.push('nuevo_campo');renderSettings()}if(removeStage){if(settings.pipeline.etapas.length>1){settings.pipeline.etapas.splice(Number(removeStage.dataset.removeStage),1);renderSettings()}}if(removeField){settings.pipeline.campos.splice(Number(removeField.dataset.removeField),1);renderSettings()}});
      document.addEventListener('click',async function(e){if(!e.target.closest('#save-settings'))return;var stages=Array.from(document.querySelectorAll('.settings-stage')).map(function(row){return {key:row.querySelector('[data-stage-key]').value,nombre:row.querySelector('[data-stage-name]').value.trim()||'Sin nombre',color:row.querySelector('[data-stage-color]').value,activa:true}}),fields=Array.from(document.querySelectorAll('[data-field-name]')).map(function(x){return x.value.trim()}).filter(Boolean);var r=await fetch('/api/settings',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({pipeline:{etapas:stages,campos:fields}})});if(r.ok){settings=await r.json();window.crmStages=settings.pipeline.etapas.filter(function(s){return s.activa!==false}).map(function(s){return [s.key,s.nombre]});renderSettings();if(typeof load==='function')load();alert('Personalización guardada')}else alert('No se pudo guardar la personalización')});
      function updateUnreadBadges(){var n=(typeof leads!=='undefined'?leads:[]).filter(function(l){return l.no_leido}).length;['unread-pipeline','unread-inbox'].forEach(function(id){var el=document.getElementById(id);if(!el)return;if(n>0){el.textContent=n>99?'99+':String(n);el.style.display='inline-block'}else{el.style.display='none'}})}
      var currentLoad=load;load=async function(){await currentLoad();renderAnalytics();decorateBotControls();updateUnreadBadges()};
      loadSettings().then(function(){window.crmStages=settings.pipeline.etapas.filter(function(s){return s.activa!==false}).map(function(s){return [s.key,s.nombre]});if(typeof load==='function')load()});setTimeout(renderAnalytics,150);window.addEventListener('resize',function(){if(window.innerWidth<900)document.body.classList.add('crm-compact')});
      window.updateUnreadBadges=updateUnreadBadges;
      window.renderAnalytics=renderAnalytics;
    })();
    </script>'''
    response.body = response.body.replace(b'</body></html>', workspace_script.encode('utf-8') + b'</body></html>', 1)
    response.body = _marca(response.body.decode("utf-8")).encode("utf-8")
    response.headers["Content-Length"] = str(len(response.body))
    return response
