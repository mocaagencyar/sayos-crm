# Guía base para replicar clientes

Este repositorio es una base white label: no tiene la marca de ninguna agencia
fija. Cualquier agencia puede clonarlo y usarlo con su propia marca y la de
cada uno de sus clientes. Cada cliente debe tener su propia instancia de
Render, su propia base PostgreSQL y sus propias credenciales de Meta/Anthropic.

## Arquitectura recomendada

```text
WhatsApp API del cliente
        ↓
     Max + FastAPI
        ↓
  PostgreSQL del cliente
        ↓
 Dashboard privado + Telegram
```

El número humano del cliente puede seguir funcionando en WhatsApp Business App para el seguimiento manual. La instancia de Max usa un número API separado, salvo que el cliente contrate una solución de coexistencia mediante un BSP/Tech Provider.

## Crear una instancia nueva

1. Duplicar este repositorio para el cliente.
2. Crear un servicio web independiente en Render conectado al repositorio.
3. Crear un proyecto PostgreSQL independiente, por ejemplo en Supabase.
4. Cargar las variables de entorno del cliente en Render.
5. Configurar `config/business.yaml`, `config/prompts.yaml` y la carpeta `knowledge/`.
6. Configurar la marca del dashboard con las variables `BRAND_*` (ver más abajo) — con la marca de la agencia o del cliente final, según corresponda. Sin esto, el cliente ve un placeholder genérico ("CRM" / "Tu Negocio").
7. Crear el número de WhatsApp Cloud API y configurar el webhook.
8. Configurar el bot de Telegram y su `TELEGRAM_CHAT_ID`.
9. Definir `DASHBOARD_USERNAME` y una contraseña única.
10. Probar salud, login, conversación, lead calificado, Telegram, dashboard y exportaciones.

## Checklist antes de entregar una instancia

- Confirmar que `/api/system/status` informa `PostgreSQL` y `production`.
- Confirmar que el dashboard muestra la marca correcta (nombre, color, logo) y no el placeholder genérico.
- Enviar una conversación de prueba y verificar que queda visible en **Bandeja**.
- Verificar extracción de nombre, rubro, presupuesto, interés y sentimiento.
- Confirmar recepción de Telegram y carga del lead en **Pipeline**.
- Probar **Seguimiento**, **Datos comerciales**, **Pausar Max**, **Cerrar**, **Descartar** y exportación CSV.
- Configurar una rutina de backup del proyecto PostgreSQL antes de comenzar campañas reales.
- Guardar en un inventario privado los IDs y nombres de cada canal; nunca poner tokens en el repositorio.

El endpoint autenticado `/api/system/status` confirma el entorno y si la instancia está usando PostgreSQL o SQLite, sin mostrar credenciales.

## Variables mínimas de producción

```env
ANTHROPIC_API_KEY=
WHATSAPP_PROVIDER=meta
META_ACCESS_TOKEN=
META_PHONE_NUMBER_ID=
META_VERIFY_TOKEN=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
DATABASE_URL=postgresql+asyncpg://...
ENVIRONMENT=production
DASHBOARD_USERNAME=
DASHBOARD_PASSWORD=
```

## Marca del dashboard (`BRAND_*`)

Todas opcionales — sin configurarlas, el dashboard usa una identidad placeholder
genérica ("CRM" / "Tu Negocio", azul). Esta base no tiene marca propia: sirve para
cualquier agencia. Para un cliente nuevo alcanza con completar estas variables
en Render con la marca de la agencia o del cliente final; no hace falta tocar
ningún archivo de código:

```env
BRAND_NAME=Nombre CRM del cliente       # título de pestaña, footer del menú
BRAND_COMPANY=Nombre corto              # texto en el header
BRAND_TAGLINE=Frase corta               # debajo del nombre, en el header
BRAND_SHORT=XX                          # 2-3 letras del mark cuando no hay logo
BRAND_COLOR=#2563eb                     # color primario (botones, acentos)
BRAND_COLOR_2=#60a5fa                   # color secundario (degradés)
BRAND_LOGO_URL=https://.../logo.png     # opcional — si no se define, se usa un mark de texto con BRAND_SHORT
```

## Regla de datos

En producción nunca usar SQLite. Render puede reemplazar el disco local durante un deploy o reinicio. PostgreSQL es la fuente permanente para leads, conversaciones, estados y canales.

## Flujo comercial

```text
Lead escribe → Max conversa → se guarda todo el chat
       ↓
Se califica → Telegram avisa → aparece en seguimiento
       ↓
Comercial responde desde su WhatsApp Business
       ↓
El equipo marca cerrado, descartado o mantiene seguimiento
```

## Canales

- WhatsApp Cloud API: disponible para Max.
- Instagram/Facebook: requieren app, permisos y webhooks de Meta.
- WhatsApp Business App + Cloud API en el mismo número: requiere Embedded Signup habilitado para BSP/Tech Provider; no asumirlo como función gratuita de una app común.

## Cambios del núcleo

Las mejoras generales del dashboard se hacen en este repositorio base. Luego se publican por Git y se actualizan las instancias de clientes después de probarlas.

Las credenciales, prompts, datos de negocio y bases de datos nunca se comparten entre clientes.

## Alcance actual del producto

El núcleo está listo para operar con WhatsApp Cloud API: calificación, memoria, Telegram, sentimiento,
pipeline, conversaciones, notas internas, control humano y exportación. Instagram y Facebook quedan como
integraciones posteriores porque su puesta en producción depende de la verificación, permisos y revisión de
Meta de cada aplicación. No deben bloquear la entrega inicial de un cliente por WhatsApp.
