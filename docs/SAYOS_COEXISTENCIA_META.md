# Sayos CRM: deploy y vinculación de WhatsApp

# Opción activa: puente propio por QR (estilo WhatsApp Web)

`WHATSAPP_PROVIDER=bridge`. Gratis y sin depender de Meta ni de Whapi.

1. CRM → **Canales** → tarjeta **WhatsApp vinculado por QR** → aparece el QR.
2. En el teléfono: WhatsApp Business → **Dispositivos vinculados → Vincular un dispositivo** → escanear.
3. Listo: lo que escriben los clientes y lo que contestás desde el teléfono entra a **Conversaciones**. Nadie responde automáticamente.

Cómo funciona: `bridge/index.mjs` (Node + Baileys) corre en el mismo servicio de Render, se conecta como dispositivo vinculado y reenvía cada mensaje al CRM firmado con un secreto interno. La sesión se guarda en PostgreSQL (tabla `wa_auth`): no hay que reescanear tras un deploy.

- `BRIDGE_ENVIO=false` → solo lectura total: el CRM no puede mandar nada por WhatsApp.
- `KEEPALIVE=true` → se pide `/health` cada 10 min para que el plan gratis de Render no se duerma (dormido no recibe mensajes; al despertar recupera los de las últimas 72 h).
- **Riesgo:** no es la API oficial (va contra los términos de WhatsApp). Usado para leer y contestar normal, el riesgo de bloqueo es bajo pero no cero. Probar primero con un número propio.
- Si el teléfono no abre WhatsApp en 14 días, WhatsApp desvincula el dispositivo: reescanear.
- Grupos, estados, canales y reacciones se ignoran. Fotos, audios y documentos aparecen como `[Imagen]`, `[Audio]`, etc.

---

# Alternativa oficial: coexistencia de Meta

Modo de esta instancia: **CRM de solo lectura** (`BOT_ENABLED=false`).
No responde nada automáticamente. Guarda lo que escriben los clientes y lo que
el equipo contesta desde el teléfono, y permite contestar a mano desde el dashboard.

**Prueba:** número de WhatsApp Business de Marcos + app de Meta de MC ("Max").
**Producción:** número de Sayos (+54 9 11 2766 0405) + app de Meta nueva propia.

---

## Parte A: app de Meta (5 min, sin romper Max)

> **No cambies nada en WhatsApp → Configuration → Webhook de la app.** Esa URL
> es la de Max de la agencia. Sayos usa un webhook propio que el CRM registra
> solo en la cuenta de WhatsApp del número vinculado (`override_callback_uri`).

1. Entrá a [developers.facebook.com/apps](https://developers.facebook.com/apps) → la app de Max.
2. **App settings → Basic**: copiá **App ID** y **App secret** (botón *Show*).
3. **Facebook Login for Business → Configurations**:
   - Si ya hay una configuración de *WhatsApp Embedded Signup*, copiá su **Configuration ID**.
   - Si no hay: *Create configuration* → tipo **WhatsApp Embedded Signup** → permisos
     `whatsapp_business_management` y `whatsapp_business_messaging` → copiá el ID.
4. **Facebook Login for Business → Settings**:
   - *Allowed domains for the JavaScript SDK*: `https://sayos-crm.onrender.com`
   - *Valid OAuth Redirect URIs*: `https://sayos-crm.onrender.com/`
   - *Login with the JavaScript SDK*: **Sí**
   (Si Render te asigna otra URL, usá esa.)
5. **Requisito de Meta:** la coexistencia solo aparece si la app es **Tech Provider**
   (o Solution Partner) con el negocio verificado. Si en el popup del paso C no
   aparece la opción de conectar la app de WhatsApp Business existente, es por
   esto. Mientras tanto, el plan B es Whapi (ver al final).

## Parte B: deploy en Render (10 min)

1. [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint** → repo `mocaagencyar/sayos-crm`.
   Crea el servicio `sayos-crm` (Docker) y la base `sayos-crm-db` (PostgreSQL), ya conectados.
2. Completá las variables que pide:

   | Variable | Valor |
   |---|---|
   | `META_APP_ID` | App ID (A.2) |
   | `META_APP_SECRET` | App secret (A.2) |
   | `META_EMBEDDED_SIGNUP_CONFIG_ID` | Configuration ID (A.3) |
   | `PUBLIC_BASE_URL` | `https://sayos-crm.onrender.com` (sin barra final) |
   | `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` | los que quieras, clave larga |
   | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | opcional, para avisos de mensajes nuevos |
   | `BRAND_LOGO_URL` | opcional (vacío = mark "SY") |

   `META_VERIFY_TOKEN` se genera solo. La marca (`BRAND_*`), `BOT_ENABLED=false`
   y `WHATSAPP_PROVIDER=meta` ya vienen cargados.
3. Esperá el deploy y abrí `https://sayos-crm.onrender.com/health` → tiene que decir
   `"negocio": "Sayos"` y `"persistencia": "PostgreSQL"`.
4. Entrá a `https://sayos-crm.onrender.com` (te lleva al login) → **Acciones → Cargar datos demo**: aparecen 7 leads de prueba
   ("Demo · …") en todas las etapas del pipeline. Se borran con *Eliminar*.

### Acceso: URL propia y clave

- La URL abre directo la pantalla de acceso (usuario + clave de `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`). La sesión dura 12 h; *Acciones → Cerrar sesión* la termina.
- 5 intentos fallidos desde la misma IP bloquean el acceso 15 minutos.
- **Dominio propio (ej. `crm.sayos.com.ar`):** Render → servicio `sayos-crm` → *Settings → Custom Domains → Add* → `crm.sayos.com.ar`. Render indica un registro **CNAME** que hay que cargar en el DNS de `sayos.com.ar` (lo administra quien tenga el dominio; hoy lo tiene Claudio). El certificado HTTPS lo emite Render solo.
- Con dominio propio, actualizar `PUBLIC_BASE_URL` y los dominios permitidos de la app de Meta (parte A.4) a `https://crm.sayos.com.ar`.

> Plan gratis: el servicio se duerme tras 15 min sin uso (el primer mensaje lo
> despierta en ~1 min) y la base gratis vence a los 30 días. Para Sayos en
> producción: web **Starter** + base **Basic-256mb**.

## Parte C: vincular tu WhatsApp Business (5 min)

Antes:
- WhatsApp Business actualizado (2.24.17 o más) en un teléfono con cámara, a mano y con internet.
- El número tiene que venir **usándose en WhatsApp Business (mandando y recibiendo) al menos 7 días seguidos**; si no, Meta rechaza la vinculación.
- El número no tiene que estar conectado a otra API o proveedor.
- Al vincular se desconectan los dispositivos enlazados (WhatsApp Web/Desktop); después se vuelven a enlazar.

1. Abrí el dashboard **en Chrome o Edge de la compu** (no en el navegador interno de una app).
2. Menú **Canales → WhatsApp Coexistence → Conectar con Meta**.
3. En el popup de Meta: iniciá sesión → elegí el **portfolio de negocio** →
   elegí **conectar tu app de WhatsApp Business existente** → ingresá tu número.
4. Meta muestra un **QR**: escanealo desde WhatsApp Business en el teléfono
   (te llega el aviso en la app) y aceptá **compartir el historial de chats**.
5. Al cerrarse el popup, el CRM muestra "Número conectado. Webhook: …/webhook".
   Por detrás canjea el código por el token, registra el webhook propio en tu
   cuenta de WhatsApp y pide la sincronización de contactos e historial.

## Parte D: probar todo

| Prueba | Resultado esperado |
|---|---|
| Desde otro teléfono, escribile a tu número | Aparece en **Conversaciones** con punto rojo de no leído (y aviso en Telegram si lo configuraste). **Nadie responde automáticamente.** |
| Contestá desde tu WhatsApp Business | La respuesta aparece en el chat del CRM como **Comercial** |
| Contestá desde el CRM (*Chat → Enviar como comercial*) | Llega al cliente y también se ve en tu teléfono. Solo funciona dentro de las 24 h desde el último mensaje del cliente (regla de Meta) |
| Cerrar oportunidades | Botones **✓ Ganado** / **✕ Perdido** en cualquier etapa; **↺ Reabrir** si fue un error |
| Pipeline | Arrastrar entre Nuevo → Contactado → Visita / medición → Presupuesto enviado → Seguimiento → Ganado/Perdido |
| Datos / Seguimiento | Valor de la oportunidad, origen, nota interna, próxima acción |
| Nuevo lead | Carga manual de una consulta que llegó por otro lado |
| Reportes / Resumen | Conversión, etapas y sentimiento por período |
| Acciones → Exportar | CSV de leads y de conversaciones (abre en Excel) |

## Desvincular

WhatsApp Business en el teléfono → **Configuración → Cuenta → Plataforma de
negocios (Business Platform)** → elegir la conexión → **Desconectar**. El número
sigue funcionando normal en el teléfono.

## Cosas a tener en cuenta

- Para que la coexistencia siga activa, Meta pide abrir WhatsApp Business en el teléfono periódicamente (al menos cada 14 días).
- La ventana de 24 h para contestar desde el CRM la abre solo un mensaje nuevo del cliente; las respuestas desde el teléfono y el historial importado no la abren.
- Contestar dentro de las 24 h es gratis. Escribirle primero a un cliente fuera de esa ventana requiere plantillas pagas (el CRM no lo hace).
- Lo que la IA no hace en este modo: completar solo rubro, presupuesto e interés. Se cargan a mano en *Datos*.

## Plan B (si Meta no habilita la coexistencia en la app de Max): Whapi

1. Cuenta en [whapi.cloud](https://whapi.cloud) → canal Sandbox (gratis: 5 chats, 150 mensajes/día) → vincular el teléfono por QR.
2. En Render: `WHATSAPP_PROVIDER=whapi` y `WHAPI_TOKEN=<token del canal>`.
3. En Whapi → Settings → Webhook: `https://sayos-crm.onrender.com/webhook`, eventos *messages* (POST).
4. Mismo resultado: lo que entra y lo que contestás desde el teléfono se ve en el CRM.

## Pasaje a producción (Sayos)

1. App de Meta nueva, en el portfolio de Sayos o de la agencia, con el negocio verificado y alta como Tech Provider.
2. Cambiar `META_APP_ID`, `META_APP_SECRET` y `META_EMBEDDED_SIGNUP_CONFIG_ID` en Render.
3. Desvincular el número de prueba y repetir la parte C con el teléfono de Claudio (+54 9 11 2766 0405).
4. Borrar los leads "Demo · …" y pasar a los planes pagos de Render.
