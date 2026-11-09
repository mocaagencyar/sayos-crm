# agent/memory.py — Memoria de conversaciones con SQLite
# Generado por AgentKit

"""
Sistema de memoria del agente Max. Guarda el historial de conversaciones
por número de teléfono usando SQLite (local) o PostgreSQL (producción en Railway).
"""

import os
import json
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, select, Integer, Boolean, text, func
from dotenv import load_dotenv

load_dotenv()

# Configuración de base de datos desde .env
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentkit.db")

# SQLAlchemy necesita el driver asyncpg para PostgreSQL. Aceptamos los formatos
# que suelen entregar los proveedores cloud (postgres:// y postgresql://).
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgresql+postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql+postgres://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Mensaje(Base):
    """Modelo de mensaje almacenado en la base de datos."""
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    role: Mapped[str] = mapped_column(String(20))       # "user" o "assistant"
    content: Mapped[str] = mapped_column(Text)
    fuente: Mapped[str] = mapped_column(String(20), default="bot")  # bot, human o user
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lead(Base):
    """Lead calificado por Max — para el dashboard y seguimiento."""
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    notificado: Mapped[bool] = mapped_column(Boolean, default=False)
    revision_notificada: Mapped[bool] = mapped_column(Boolean, default=False)
    cerrado: Mapped[bool] = mapped_column(Boolean, default=False)
    descartado: Mapped[bool] = mapped_column(Boolean, default=False)
    # Datos extraídos de la conversación
    nombre: Mapped[str] = mapped_column(String(100), default="No indicó")
    rubro: Mapped[str] = mapped_column(String(100), default="No indicó")
    presupuesto: Mapped[str] = mapped_column(String(100), default="No indicó")
    interes: Mapped[str] = mapped_column(Text, default="No indicó")
    sentiment_score: Mapped[int] = mapped_column(Integer, default=50)
    sentiment_label: Mapped[str] = mapped_column(String(30), default="neutral")
    resumen: Mapped[str] = mapped_column(Text, default="No disponible")
    nota: Mapped[str] = mapped_column(Text, default="")
    proxima_accion: Mapped[str] = mapped_column(String(300), default="")
    etapa: Mapped[str] = mapped_column(String(30), default="seguimiento")
    fecha_proxima_accion: Mapped[str] = mapped_column(String(30), default="")
    valor_oportunidad: Mapped[str] = mapped_column(String(100), default="")
    origen: Mapped[str] = mapped_column(String(100), default="WhatsApp")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Actividad reciente — para ordenar como cualquier CRM (el que acaba de
    # escribir arriba de todo) y para la campanita de "no leído por un humano"
    ultima_actividad: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    no_leido: Mapped[bool] = mapped_column(Boolean, default=True)
    # Calificado — lo pone Max automáticamente cuando detecta que calificó,
    # pero también se puede marcar/desmarcar a mano desde el dashboard para
    # tener la métrica real de conversión del funnel.
    calificado: Mapped[bool] = mapped_column(Boolean, default=False)


class Canal(Base):
    """Canal conectado al CRM. Las credenciales nunca se devuelven al navegador."""
    __tablename__ = "canales"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100))
    tipo: Mapped[str] = mapped_column(String(30), default="whatsapp")
    phone_number_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    access_token: Mapped[str] = mapped_column(Text)
    verify_token: Mapped[str] = mapped_column(String(200), default="mcgrowth-webhook-2026")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    coexistencia: Mapped[bool] = mapped_column(Boolean, default=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ControlContacto(Base):
    """Controla si Max puede responder o si el equipo tomó la conversación."""
    __tablename__ = "control_contactos"

    telefono: Mapped[str] = mapped_column(String(50), primary_key=True)
    bot_activo: Mapped[bool] = mapped_column(Boolean, default=True)
    responsable: Mapped[str] = mapped_column(String(100), default="Max")
    motivo: Mapped[str] = mapped_column(String(200), default="")
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Configuracion(Base):
    """Preferencias editables del workspace, sin depender de prompts o comandos."""
    __tablename__ = "configuracion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clave: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    valor: Mapped[str] = mapped_column(Text, default="{}")
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


async def inicializar_db():
    """Crea las tablas si no existen. Se llama al arrancar el servidor."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if DATABASE_URL.startswith("sqlite"):
            columnas = await conn.execute(text("PRAGMA table_info(leads)"))
            existentes = {fila[1] for fila in columnas.fetchall()}
            nuevas = {
                "revision_notificada": "BOOLEAN DEFAULT 0",
                "sentiment_score": "INTEGER DEFAULT 50",
                "sentiment_label": "VARCHAR(30) DEFAULT 'neutral'",
                "resumen": "TEXT DEFAULT 'No disponible'",
                "nota": "TEXT DEFAULT ''",
                "proxima_accion": "VARCHAR(300) DEFAULT ''",
                "etapa": "VARCHAR(30) DEFAULT 'seguimiento'",
                "fecha_proxima_accion": "VARCHAR(30) DEFAULT ''",
                "valor_oportunidad": "VARCHAR(100) DEFAULT ''",
                "origen": "VARCHAR(100) DEFAULT 'WhatsApp'",
                "no_leido": "BOOLEAN DEFAULT 0",
            }
            for nombre, tipo in nuevas.items():
                if nombre not in existentes:
                    await conn.execute(text(f"ALTER TABLE leads ADD COLUMN {nombre} {tipo}"))
            if "calificado" not in existentes:
                await conn.execute(text("ALTER TABLE leads ADD COLUMN calificado BOOLEAN DEFAULT 0"))
                await conn.execute(text("UPDATE leads SET calificado = notificado"))
            if "ultima_actividad" not in existentes:
                await conn.execute(text("ALTER TABLE leads ADD COLUMN ultima_actividad DATETIME"))
                await conn.execute(text("UPDATE leads SET ultima_actividad = timestamp WHERE ultima_actividad IS NULL"))
            columnas_mensajes = await conn.execute(text("PRAGMA table_info(mensajes)"))
            existentes_mensajes = {fila[1] for fila in columnas_mensajes.fetchall()}
            if "fuente" not in existentes_mensajes:
                await conn.execute(text("ALTER TABLE mensajes ADD COLUMN fuente VARCHAR(20) DEFAULT 'bot'"))
            columnas_canales = await conn.execute(text("PRAGMA table_info(canales)"))
            existentes_canales = {fila[1] for fila in columnas_canales.fetchall()}
            if "coexistencia" not in existentes_canales:
                await conn.execute(text("ALTER TABLE canales ADD COLUMN coexistencia BOOLEAN DEFAULT 0"))
        else:
            # create_all no modifica tablas ya existentes. Estas migraciones
            # pequeñas mantienen compatible la base de datos de clientes
            # cuando publicamos una nueva versión del núcleo.
            columnas_pg = await conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='leads'"))
            existentes_pg = {fila[0] for fila in columnas_pg.fetchall()}
            await conn.execute(text("ALTER TABLE mensajes ADD COLUMN IF NOT EXISTS fuente VARCHAR(20) DEFAULT 'bot'"))
            await conn.execute(text("ALTER TABLE canales ADD COLUMN IF NOT EXISTS coexistencia BOOLEAN DEFAULT FALSE"))
            await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS nota TEXT DEFAULT ''"))
            await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS proxima_accion VARCHAR(300) DEFAULT ''"))
            await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS etapa VARCHAR(30) DEFAULT 'seguimiento'"))
            await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS fecha_proxima_accion VARCHAR(30) DEFAULT ''"))
            await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS valor_oportunidad VARCHAR(100) DEFAULT ''"))
            await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS origen VARCHAR(100) DEFAULT 'WhatsApp'"))
            await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS revision_notificada BOOLEAN DEFAULT FALSE"))
            await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS no_leido BOOLEAN DEFAULT FALSE"))
            if "calificado" not in existentes_pg:
                await conn.execute(text("ALTER TABLE leads ADD COLUMN calificado BOOLEAN DEFAULT FALSE"))
                await conn.execute(text("UPDATE leads SET calificado = notificado"))
            await conn.execute(text("ALTER TABLE leads ADD COLUMN IF NOT EXISTS ultima_actividad TIMESTAMP"))
            await conn.execute(text("UPDATE leads SET ultima_actividad = timestamp WHERE ultima_actividad IS NULL"))

    # Se consulta después de cerrar la transacción anterior. En PostgreSQL,
    # otro connection no puede ver la tabla hasta que create_all fue confirmado.
    async with async_session() as session:
        if not (await session.execute(select(Canal))).scalars().first():
            token = os.getenv("META_ACCESS_TOKEN")
            phone_id = os.getenv("META_PHONE_NUMBER_ID")
            if token and phone_id:
                session.add(Canal(nombre="WhatsApp principal", tipo="whatsapp", phone_number_id=phone_id, access_token=token, verify_token=os.getenv("META_VERIFY_TOKEN", "mcgrowth-webhook-2026"), coexistencia=os.getenv("META_COEXISTENCE", "false").lower() == "true"))
                await session.commit()


async def obtener_canal(phone_number_id: str | None):
    if not phone_number_id:
        return None
    async with async_session() as session:
        result = await session.execute(select(Canal).where(Canal.phone_number_id == phone_number_id, Canal.activo == True))
        return result.scalar_one_or_none()


async def obtener_canales() -> list[dict]:
    async with async_session() as session:
        result = await session.execute(select(Canal).order_by(Canal.timestamp.asc()))
        return [{"id": c.id, "nombre": c.nombre, "tipo": c.tipo, "phone_number_id": c.phone_number_id, "activo": c.activo, "coexistencia": c.coexistencia, "configurado": bool(c.access_token)} for c in result.scalars().all()]


async def guardar_canal(nombre: str, tipo: str, phone_number_id: str, access_token: str, verify_token: str) -> dict:
    async with async_session() as session:
        result = await session.execute(select(Canal).where(Canal.phone_number_id == phone_number_id))
        canal = result.scalar_one_or_none()
        if canal:
            canal.nombre, canal.tipo, canal.access_token, canal.verify_token, canal.activo = nombre, tipo, access_token, verify_token, True
        else:
            canal = Canal(nombre=nombre, tipo=tipo, phone_number_id=phone_number_id, access_token=access_token, verify_token=verify_token, activo=True)
            session.add(canal)
        await session.commit()
        return {"id": canal.id, "nombre": canal.nombre, "tipo": canal.tipo, "phone_number_id": canal.phone_number_id, "activo": canal.activo, "configurado": True}


async def alternar_canal(canal_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(select(Canal).where(Canal.id == canal_id))
        canal = result.scalar_one_or_none()
        if not canal:
            return False
        canal.activo = not canal.activo
        await session.commit()
        return canal.activo


async def guardar_mensaje(telefono: str, role: str, content: str, fuente: str = "bot"):
    """
    Guarda un mensaje en el historial de conversación.

    Args:
        telefono: Número de teléfono del prospecto
        role: "user" (prospecto) o "assistant" (Max)
        content: Texto del mensaje
    """
    async with async_session() as session:
        mensaje = Mensaje(
            telefono=telefono,
            role=role,
            content=content,
            fuente=fuente,
            timestamp=datetime.utcnow()
        )
        session.add(mensaje)
        await session.commit()


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    """
    Recupera los últimos N mensajes de una conversación.

    Args:
        telefono: Número de teléfono del prospecto
        limite: Máximo de mensajes a recuperar (default: 20 = ~10 intercambios)

    Returns:
        Lista de dicts con role y content, en orden cronológico
    """
    async with async_session() as session:
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(limite)
        )
        result = await session.execute(query)
        mensajes = result.scalars().all()

        # Invertir para orden cronológico (los más recientes estaban primero)
        mensajes.reverse()

        return [
            {"role": msg.role, "content": msg.content}
            for msg in mensajes
        ]


async def registrar_lead(telefono: str, notificado: bool = False) -> bool:
    """
    Registra un lead calificado. Si ya existe, no hace nada.

    Returns:
        True si fue registrado por primera vez (nuevo lead)
        False si ya existía (ya fue notificado antes)
    """
    async with async_session() as session:
        query = select(Lead).where(Lead.telefono == telefono)
        result = await session.execute(query)
        existente = result.scalar_one_or_none()

        if existente:
            return False  # Ya registrado

        lead = Lead(telefono=telefono, notificado=notificado, cerrado=False, descartado=False)
        session.add(lead)
        await session.commit()
        return True


async def registrar_actividad(telefono: str) -> bool:
    """
    Actualiza la marca de actividad cada vez que el contacto escribe, y lo
    deja marcado como no leído por un humano — independientemente de que
    Max ya le haya contestado. Se llama en CADA mensaje entrante.
    """
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False
        lead.ultima_actividad = datetime.utcnow()
        lead.no_leido = True
        await session.commit()
        return True


async def marcar_leido(telefono: str) -> bool:
    """Marca que un humano ya vio la conversación. Se llama al abrir el chat."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False
        lead.no_leido = False
        await session.commit()
        return True


async def marcar_lead_notificado(telefono: str) -> bool:
    """Marca que el lead ya fue enviado al equipo como calificado (y lo cuenta como calificado)."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False
        lead.notificado = True
        lead.calificado = True
        await session.commit()
        return True


async def marcar_calificado(telefono: str, calificado: bool) -> bool:
    """Marca/desmarca a mano si un lead califica, para la métrica de conversión del funnel."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False
        lead.calificado = calificado
        await session.commit()
        return True


async def marcar_revision_notificada(telefono: str) -> bool:
    """Evita repetir alertas cuando un caso requiere revisión humana."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False
        lead.revision_notificada = True
        await session.commit()
        return True


async def actualizar_info_lead(telefono: str, nombre: str, rubro: str, presupuesto: str, interes: str,
                              sentiment_score: int = 50, sentiment_label: str = "neutral",
                              resumen: str = "No disponible"):
    """Guarda los datos extraídos de la conversación en el lead."""
    async with async_session() as session:
        query = select(Lead).where(Lead.telefono == telefono)
        result = await session.execute(query)
        lead = result.scalar_one_or_none()
        if lead:
            lead.nombre = nombre
            lead.rubro = rubro
            lead.presupuesto = presupuesto
            lead.interes = interes
            lead.sentiment_score = max(0, min(100, int(sentiment_score or 50)))
            lead.sentiment_label = sentiment_label or "neutral"
            lead.resumen = resumen or "No disponible"
            await session.commit()


async def marcar_lead_cerrado(telefono: str) -> bool:
    """Marca un lead como cerrado (cliente ganado)."""
    async with async_session() as session:
        query = select(Lead).where(Lead.telefono == telefono)
        result = await session.execute(query)
        lead = result.scalar_one_or_none()
        if lead:
            lead.cerrado = True
            lead.descartado = False
            await session.commit()
            return True
        return False


async def marcar_lead_descartado(telefono: str) -> bool:
    """Marca un lead como descartado (no avanzó)."""
    async with async_session() as session:
        query = select(Lead).where(Lead.telefono == telefono)
        result = await session.execute(query)
        lead = result.scalar_one_or_none()
        if lead:
            lead.descartado = True
            lead.cerrado = False
            await session.commit()
            return True
        return False


async def cambiar_estado_lead(telefono: str, estado: str) -> bool:
    """Cambia el estado del lead desde el pipeline."""
    if estado not in {"nuevo", "contactado", "propuesta", "negociacion", "seguimiento", "cerrado", "ganado", "descartado", "perdido"}:
        return False
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False
        lead.etapa = estado
        lead.cerrado = estado in {"cerrado", "ganado"}
        lead.descartado = estado in {"descartado", "perdido"}
        await session.commit()
        return True


async def actualizar_seguimiento_lead(telefono: str, nota: str = "", proxima_accion: str = "") -> bool:
    """Guarda información interna del seguimiento comercial del lead."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False
        lead.nota = (nota or "").strip()[:2000]
        lead.proxima_accion = (proxima_accion or "").strip()[:300]
        await session.commit()
        return True


async def actualizar_nombre_lead(telefono: str, nombre: str) -> bool:
    """Permite completar o corregir el nombre desde el CRM."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False
        lead.nombre = (nombre or "No indicó").strip()[:100] or "No indicó"
        await session.commit()
        return True


async def actualizar_datos_oportunidad(telefono: str, fecha_proxima_accion: str = "", valor_oportunidad: str = "", origen: str = "") -> bool:
    """Guarda datos comerciales adicionales de la oportunidad."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False
        lead.fecha_proxima_accion = (fecha_proxima_accion or "").strip()[:30]
        lead.valor_oportunidad = (valor_oportunidad or "").strip()[:100]
        if origen and origen.strip():
            lead.origen = origen.strip()[:100]
        await session.commit()
        return True


CONFIG_DEFAULTS = {
    "pipeline": {
        "etapas": [
            {"key": "nuevo", "nombre": "Nuevo", "color": "#60a5fa", "activa": True},
            {"key": "contactado", "nombre": "Contactado", "color": "#fbbf24", "activa": True},
            {"key": "propuesta", "nombre": "Propuesta", "color": "#a78bfa", "activa": True},
            {"key": "negociacion", "nombre": "Negociación", "color": "#fb923c", "activa": True},
            {"key": "ganado", "nombre": "Ganado", "color": "#4ade80", "activa": True},
            {"key": "perdido", "nombre": "Perdido", "color": "#a1a1aa", "activa": True},
        ],
        "campos": ["rubro", "presupuesto", "interes", "valor_oportunidad", "origen"],
    },
    "workspace": {"nombre": "MC Growth OS", "descripcion": "Lead intelligence"},
}


async def obtener_configuracion() -> dict:
    """Devuelve preferencias del workspace con defaults seguros para clientes nuevos."""
    async with async_session() as session:
        result = await session.execute(select(Configuracion))
        guardadas = {fila.clave: fila.valor for fila in result.scalars().all()}
    config = json.loads(json.dumps(CONFIG_DEFAULTS))
    for clave, valor in guardadas.items():
        try:
            config[clave] = json.loads(valor)
        except (TypeError, json.JSONDecodeError):
            continue
    return config


async def guardar_configuracion(config: dict) -> dict:
    """Actualiza únicamente las secciones configurables del CRM."""
    permitidas = {"pipeline", "workspace"}
    limpia = {k: config[k] for k in permitidas if k in config and isinstance(config[k], dict)}
    async with async_session() as session:
        for clave, valor in limpia.items():
            result = await session.execute(select(Configuracion).where(Configuracion.clave == clave))
            fila = result.scalar_one_or_none()
            if fila:
                fila.valor = json.dumps(valor, ensure_ascii=False)
                fila.actualizado = datetime.utcnow()
            else:
                session.add(Configuracion(clave=clave, valor=json.dumps(valor, ensure_ascii=False)))
        await session.commit()
    return await obtener_configuracion()


async def eliminar_lead(telefono: str) -> bool:
    """Elimina explícitamente un lead y su conversación asociada."""
    async with async_session() as session:
        result = await session.execute(select(Lead).where(Lead.telefono == telefono))
        lead = result.scalar_one_or_none()
        if not lead:
            return False

        mensajes = await session.execute(select(Mensaje).where(Mensaje.telefono == telefono))
        for mensaje in mensajes.scalars().all():
            await session.delete(mensaje)
        await session.delete(lead)
        await session.commit()
        return True


async def obtener_leads(solo_abiertos: bool = False) -> list[dict]:
    """Retorna todos los leads registrados para el dashboard."""
    async with async_session() as session:
        query = select(Lead).order_by(Lead.ultima_actividad.desc())
        if solo_abiertos:
            query = query.where(Lead.cerrado == False)
        result = await session.execute(query)
        leads = result.scalars().all()
        controls_result = await session.execute(select(ControlContacto))
        controls = {control.telefono: control.bot_activo for control in controls_result.scalars().all()}
        return [
            {
                "id": l.id,
                "telefono": l.telefono,
                "notificado": l.notificado,
                "revision_notificada": l.revision_notificada,
                "cerrado": l.cerrado,
                "descartado": l.descartado,
                "nombre": l.nombre,
                "rubro": l.rubro,
                "presupuesto": l.presupuesto,
                "interes": l.interes,
                "sentiment_score": l.sentiment_score or 50,
                "sentiment_label": l.sentiment_label or "neutral",
                "resumen": l.resumen or "No disponible",
                "nota": l.nota or "",
                "proxima_accion": l.proxima_accion or "",
                "etapa": l.etapa or ("cerrado" if l.cerrado else "descartado" if l.descartado else "seguimiento"),
                "fecha_proxima_accion": l.fecha_proxima_accion or "",
                "valor_oportunidad": l.valor_oportunidad or "",
                "origen": l.origen or "WhatsApp",
                "bot_activo": controls.get(l.telefono, True),
                "no_leido": l.no_leido,
                "calificado": l.calificado,
                "ultima_actividad": (l.ultima_actividad or l.timestamp).isoformat(),
                "timestamp": l.timestamp.isoformat(),
            }
            for l in leads
        ]


async def obtener_conversacion(telefono: str) -> list[dict]:
    """Devuelve la conversación completa de un lead para verla en el dashboard."""
    async with async_session() as session:
        query = select(Mensaje).where(Mensaje.telefono == telefono).order_by(Mensaje.timestamp.asc())
        result = await session.execute(query)
        return [
            {"role": mensaje.role, "content": mensaje.content,
             "fuente": mensaje.fuente or "bot",
             "timestamp": mensaje.timestamp.isoformat()}
            for mensaje in result.scalars().all()
        ]


async def obtener_conversaciones() -> list[dict]:
    """Lista todos los contactos que iniciaron una conversación con Max."""
    async with async_session() as session:
        consulta = (
            select(Mensaje.telefono, func.max(Mensaje.timestamp), func.count(Mensaje.id))
            .group_by(Mensaje.telefono)
            .order_by(func.max(Mensaje.timestamp).desc())
        )
        result = await session.execute(consulta)
        return [
            {"telefono": telefono, "ultimo_mensaje": ultimo.isoformat(), "mensajes": cantidad}
            for telefono, ultimo, cantidad in result.all()
        ]


async def obtener_control_contacto(telefono: str) -> dict:
    async with async_session() as session:
        result = await session.execute(select(ControlContacto).where(ControlContacto.telefono == telefono))
        control = result.scalar_one_or_none()
        if not control:
            return {"telefono": telefono, "bot_activo": True, "responsable": "Max", "motivo": ""}
        return {"telefono": control.telefono, "bot_activo": control.bot_activo, "responsable": control.responsable, "motivo": control.motivo, "actualizado": control.actualizado.isoformat()}


async def establecer_control_contacto(telefono: str, bot_activo: bool, responsable: str = "Equipo comercial", motivo: str = "Toma manual") -> dict:
    async with async_session() as session:
        result = await session.execute(select(ControlContacto).where(ControlContacto.telefono == telefono))
        control = result.scalar_one_or_none()
        if not control:
            control = ControlContacto(telefono=telefono)
            session.add(control)
        control.bot_activo = bot_activo
        control.responsable = "Max" if bot_activo else responsable
        control.motivo = "" if bot_activo else motivo
        control.actualizado = datetime.utcnow()
        await session.commit()
        return {"telefono": telefono, "bot_activo": control.bot_activo, "responsable": control.responsable, "motivo": control.motivo, "actualizado": control.actualizado.isoformat()}


async def obtener_todos_los_mensajes() -> list[dict]:
    """Devuelve todos los mensajes para exportación y auditoría."""
    async with async_session() as session:
        result = await session.execute(select(Mensaje).order_by(Mensaje.timestamp.asc()))
        return [
            {"telefono": m.telefono, "role": m.role, "content": m.content,
             "timestamp": m.timestamp.isoformat()}
            for m in result.scalars().all()
        ]


async def limpiar_historial(telefono: str):
    """Borra todo el historial de conversación de un número. Útil para testing."""
    async with async_session() as session:
        query = select(Mensaje).where(Mensaje.telefono == telefono)
        result = await session.execute(query)
        mensajes = result.scalars().all()
        for msg in mensajes:
            await session.delete(msg)
        await session.commit()
