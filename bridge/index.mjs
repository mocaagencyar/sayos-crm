// bridge/index.mjs — Puente WhatsApp Web → CRM
//
// Se vincula al WhatsApp (Business o común) como un dispositivo más, igual que
// WhatsApp Web, escaneando un QR. Reenvía al CRM:
//   - los mensajes que escriben los clientes
//   - las respuestas que el equipo manda desde el teléfono
// No responde nada por su cuenta. Solo envía si el CRM se lo pide (respuesta
// manual desde el dashboard) y si BRIDGE_ENVIO no está en "false".
//
// La sesión se guarda en PostgreSQL (tabla wa_auth): sobrevive a deploys y
// reinicios de Render sin volver a escanear el QR.
//
// Escucha SOLO en 127.0.0.1 (no es accesible desde internet). El CRM le habla
// con el secreto compartido BRIDGE_SECRET.

import * as B from 'baileys'
import pino from 'pino'
import QRCode from 'qrcode'
import pg from 'pg'
import http from 'node:http'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

// ── Compatibilidad entre versiones de Baileys (v6 CommonJS / v7 ESM) ──────
const pick = (n) => B[n] ?? B.default?.[n]
const makeWASocket =
  (typeof B.default === 'function' ? B.default : null) ||
  pick('makeWASocket') ||
  B.default?.default
const DisconnectReason = pick('DisconnectReason') || { loggedOut: 401 }
const initAuthCreds = pick('initAuthCreds')
const BufferJSON = pick('BufferJSON')
const proto = pick('proto')
const fetchLatestBaileysVersion = pick('fetchLatestBaileysVersion')
const fetchLatestWaWebVersion = pick('fetchLatestWaWebVersion')
const Browsers = pick('Browsers')
const makeCacheableSignalKeyStore = pick('makeCacheableSignalKeyStore')
const generateMessageID = pick('generateMessageIDV2') || pick('generateMessageID')

// ── Configuración ─────────────────────────────────────────────────────────
const SECRET = process.env.BRIDGE_SECRET || ''
const PUERTO_PUENTE = Number(process.env.BRIDGE_PORT || 3001)
const PUERTO_CRM = Number(process.env.PORT || 8000)
const ENVIO_HABILITADO = (process.env.BRIDGE_ENVIO || 'true').toLowerCase() !== 'false'
const URL_PUBLICA = (process.env.PUBLIC_BASE_URL || '').replace(/\/$/, '')
const KEEPALIVE = (process.env.KEEPALIVE || 'true').toLowerCase() !== 'false'
// WhatsApp valida el navegador declarado: tiene que ser uno real (Chrome,
// Safari, Firefox, Edge). Un nombre inventado hace fallar la vinculación.
const NAVEGADOR = process.env.BRIDGE_BROWSER || 'Chrome'
const logger = pino({ level: process.env.BRIDGE_LOG || 'warn' })

if (!SECRET) {
  console.error('[bridge] Falta BRIDGE_SECRET; no arranco.')
  process.exit(1)
}
if (!process.env.DATABASE_URL || !process.env.DATABASE_URL.startsWith('postgres')) {
  console.error('[bridge] DATABASE_URL tiene que ser PostgreSQL para guardar la sesión.')
  process.exit(1)
}

const dbUrl = process.env.DATABASE_URL.replace(/^postgresql\+\w+:\/\//, 'postgresql://')
const pool = new pg.Pool({
  connectionString: dbUrl,
  // URL externa de Render → SSL; URL interna (red privada) → sin SSL
  ssl: /\.render\.com/.test(dbUrl) ? { rejectUnauthorized: false } : false,
  max: 4,
})

// ── Sesión en PostgreSQL (mismo esquema que useMultiFileAuthState) ────────
async function sesionPostgres() {
  await pool.query('CREATE TABLE IF NOT EXISTS wa_auth (k TEXT PRIMARY KEY, v TEXT NOT NULL)')
  const leer = async (k) => {
    const r = await pool.query('SELECT v FROM wa_auth WHERE k = $1', [k])
    return r.rows[0] ? JSON.parse(r.rows[0].v, BufferJSON.reviver) : null
  }
  const escribir = (k, data) =>
    pool.query(
      'INSERT INTO wa_auth (k, v) VALUES ($1, $2) ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v',
      [k, JSON.stringify(data, BufferJSON.replacer)]
    )
  const borrar = (k) => pool.query('DELETE FROM wa_auth WHERE k = $1', [k])
  const creds = (await leer('creds')) || initAuthCreds()
  return {
    state: {
      creds,
      keys: {
        get: async (tipo, ids) => {
          const data = {}
          await Promise.all(
            ids.map(async (id) => {
              let valor = await leer(`${tipo}-${id}`)
              if (tipo === 'app-state-sync-key' && valor && proto?.Message?.AppStateSyncKeyData) {
                valor = proto.Message.AppStateSyncKeyData.fromObject(valor)
              }
              data[id] = valor
            })
          )
          return data
        },
        set: async (data) => {
          const tareas = []
          for (const categoria in data) {
            for (const id in data[categoria]) {
              const valor = data[categoria][id]
              const k = `${categoria}-${id}`
              tareas.push(valor ? escribir(k, valor) : borrar(k))
            }
          }
          await Promise.all(tareas)
        },
      },
    },
    guardarCreds: () => escribir('creds', creds),
  }
}

const borrarSesion = () => pool.query('DELETE FROM wa_auth')

// ── Estado del puente ─────────────────────────────────────────────────────
let sock = null
let estado = 'iniciando' // iniciando | qr | conectado | reconectando | desconectado
let qrDataUrl = ''
let numero = ''
let ultimoError = ''
let conectando = false
let credsActuales = null
let codigoVinculacion = ''
const vistos = new Map() // id → timestamp (evita duplicados)
const enviadosPorCrm = new Set() // ids de mensajes que mandó el CRM (no reenviarlos)
const enviosRecientes = [] // {telefono, texto, ts} por si el id no está disponible

function recordar(id) {
  vistos.set(id, Date.now())
  if (vistos.size > 5000) {
    const limite = Date.now() - 6 * 3600e3
    for (const [k, t] of vistos) if (t < limite) vistos.delete(k)
  }
}

function soloDigitos(jid) {
  return String(jid || '').split('@')[0].split(':')[0].replace(/\D/g, '')
}

function extraerTexto(msg) {
  if (!msg) return ''
  const interno =
    msg.ephemeralMessage?.message ||
    msg.viewOnceMessage?.message ||
    msg.viewOnceMessageV2?.message ||
    msg.documentWithCaptionMessage?.message ||
    msg.editedMessage?.message
  if (interno) return extraerTexto(interno)
  const conLeyenda = (etiqueta, m) => etiqueta + (m?.caption ? ' ' + m.caption : '')
  if (msg.conversation) return msg.conversation
  if (msg.extendedTextMessage?.text) return msg.extendedTextMessage.text
  if (msg.imageMessage) return conLeyenda('[Imagen]', msg.imageMessage)
  if (msg.videoMessage) return conLeyenda('[Video]', msg.videoMessage)
  if (msg.audioMessage) return '[Audio]'
  if (msg.documentMessage) return '[Documento] ' + (msg.documentMessage.fileName || '')
  if (msg.stickerMessage) return '[Sticker]'
  if (msg.locationMessage) return '[Ubicación]'
  if (msg.contactMessage) return '[Contacto] ' + (msg.contactMessage.displayName || '')
  return '' // reacciones, mensajes de protocolo, etc.
}

function esEnvioDelCrm(id, telefono, texto) {
  if (enviadosPorCrm.has(id)) return true
  const ahora = Date.now()
  const i = enviosRecientes.findIndex((e) => e.telefono === telefono && e.texto === texto && ahora - e.ts < 30000)
  if (i >= 0) {
    enviosRecientes.splice(i, 1)
    return true
  }
  return false
}

async function telefonoDe(m) {
  const jid = m.key.remoteJid || ''
  if (!jid.endsWith('@lid')) return soloDigitos(jid)
  // Chats con identificador anónimo (LID): buscar el número real
  const alt = m.key.remoteJidAlt || m.key.senderPn || ''
  if (alt) return soloDigitos(alt)
  try {
    const pn = await sock?.signalRepository?.lidMapping?.getPNForLID?.(jid)
    if (pn) return soloDigitos(pn)
  } catch (_) {}
  return 'lid' + soloDigitos(jid)
}

async function reenviar(payload, intento = 0) {
  try {
    const r = await fetch(`http://127.0.0.1:${PUERTO_CRM}/webhook`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-bridge-secret': SECRET },
      body: JSON.stringify({ bridge: true, messages: [payload] }),
    })
    if (!r.ok) throw new Error('HTTP ' + r.status)
  } catch (e) {
    if (intento < 6) setTimeout(() => reenviar(payload, intento + 1), 2000 * (intento + 1))
    else console.error('[bridge] No pude entregar un mensaje al CRM:', e.message)
  }
}

async function procesar(m, tipo) {
  const id = m.key?.id
  if (!id || vistos.has(id)) return
  recordar(id)
  const jid = m.key.remoteJid || ''
  if (!jid || jid.endsWith('@g.us') || jid.endsWith('@broadcast') || jid.endsWith('@newsletter')) return
  const ts = Number(m.messageTimestamp || 0) * 1000
  // Historial viejo no; mensajes recibidos mientras el servidor dormía, sí (72 h)
  if (ts && Date.now() - ts > 72 * 3600e3) return
  const texto = extraerTexto(m.message)
  if (!texto) return
  const telefono = await telefonoDe(m)
  if (!telefono) return
  const fromMe = !!m.key.fromMe
  if (fromMe && esEnvioDelCrm(id, telefono, texto)) return // el CRM ya lo guardó
  await reenviar({
    id,
    telefono,
    texto,
    from_me: fromMe,
    origen: fromMe ? 'human' : 'user',
    nombre: fromMe ? '' : m.pushName || '',
    timestamp: ts,
    tipo,
  })
}

// ── Conexión a WhatsApp ───────────────────────────────────────────────────
async function conectar() {
  if (conectando) return
  conectando = true
  try {
    try { sock?.end?.(undefined) } catch (_) {}
    const { state, guardarCreds } = await sesionPostgres()
    credsActuales = state.creds
    // Versión vigente de WhatsApp Web (la de la librería puede estar vieja)
    let version
    try { if (fetchLatestWaWebVersion) ({ version } = await fetchLatestWaWebVersion({})) } catch (_) {}
    if (!version) { try { ({ version } = await fetchLatestBaileysVersion()) } catch (_) {} }
    console.log('[bridge] Conectando con WhatsApp Web', version ? version.join('.') : '(versión por defecto)', '· registrado:', !!state.creds.registered)
    sock = makeWASocket({
      ...(version ? { version } : {}),
      auth: {
        creds: state.creds,
        keys: makeCacheableSignalKeyStore ? makeCacheableSignalKeyStore(state.keys, logger) : state.keys,
      },
      logger,
      browser: Browsers?.macOS ? Browsers.macOS(NAVEGADOR) : ['Mac OS', NAVEGADOR, '14.4.1'],
      markOnlineOnConnect: false, // así el teléfono sigue recibiendo notificaciones
      syncFullHistory: false,
      printQRInTerminal: false,
    })
    sock.ev.on('creds.update', guardarCreds)
    sock.ev.on('connection.update', async (u) => {
      if (u.qr) {
        estado = 'qr'
        qrDataUrl = await QRCode.toDataURL(u.qr, { margin: 1, width: 300 })
      }
      if (u.connection === 'open') {
        estado = 'conectado'
        qrDataUrl = ''
        codigoVinculacion = ''
        ultimoError = ''
        numero = soloDigitos(sock.user?.id)
        console.log('[bridge] WhatsApp conectado:', numero)
      }
      if (u.connection === 'close') {
        const codigo = u.lastDisconnect?.error?.output?.statusCode
        ultimoError = u.lastDisconnect?.error?.message || ''
        console.warn('[bridge] Conexión cerrada · código', codigo, '·', ultimoError)
        if (codigo === DisconnectReason.loggedOut) {
          console.log('[bridge] Sesión cerrada desde el teléfono; espero un QR nuevo.')
          await borrarSesion()
          estado = 'desconectado'
          numero = ''
          setTimeout(conectar, 1500)
        } else {
          estado = 'reconectando'
          setTimeout(conectar, 4000)
        }
      }
    })
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
      for (const m of messages || []) {
        try { await procesar(m, type) } catch (e) { console.error('[bridge] Error procesando mensaje:', e.message) }
      }
    })
  } catch (e) {
    ultimoError = e.message
    estado = 'reconectando'
    console.error('[bridge] Error al conectar:', e.message)
    setTimeout(conectar, 8000)
  } finally {
    conectando = false
  }
}

// ── API interna para el CRM (solo 127.0.0.1) ──────────────────────────────
function responder(res, codigo, obj) {
  res.writeHead(codigo, { 'content-type': 'application/json' })
  res.end(JSON.stringify(obj))
}

async function leerJson(req) {
  let datos = ''
  for await (const parte of req) {
    datos += parte
    if (datos.length > 100000) break
  }
  try { return JSON.parse(datos || '{}') } catch (_) { return {} }
}

const servidor = http.createServer(async (req, res) => {
  if (req.headers['x-bridge-secret'] !== SECRET) return responder(res, 401, { error: 'no autorizado' })
  try {
    if (req.method === 'GET' && req.url === '/status') {
      return responder(res, 200, { estado, qr: qrDataUrl, numero, codigo: codigoVinculacion, envio_habilitado: ENVIO_HABILITADO, error: ultimoError })
    }
    if (req.method === 'POST' && req.url === '/send') {
      if (!ENVIO_HABILITADO) return responder(res, 403, { error: 'El envío desde el CRM está deshabilitado (BRIDGE_ENVIO=false)' })
      if (estado !== 'conectado' || !sock) return responder(res, 503, { error: 'WhatsApp no está conectado' })
      const { telefono, texto } = await leerJson(req)
      const digitos = soloDigitos(telefono)
      if (!digitos || !texto) return responder(res, 400, { error: 'Faltan teléfono o texto' })
      const messageId = generateMessageID ? generateMessageID(sock.user?.id) : undefined
      if (messageId) enviadosPorCrm.add(messageId)
      enviosRecientes.push({ telefono: digitos, texto, ts: Date.now() })
      const r = await sock.sendMessage(`${digitos}@s.whatsapp.net`, { text: texto }, messageId ? { messageId } : {})
      if (r?.key?.id) enviadosPorCrm.add(r.key.id)
      return responder(res, 200, { ok: true, id: r?.key?.id || messageId || '' })
    }
    if (req.method === 'POST' && req.url === '/pair') {
      // Vinculación con número de teléfono: WhatsApp muestra un código de 8
      // caracteres que se tipea en el teléfono (alternativa al QR).
      if (!sock || estado === 'conectado' || credsActuales?.registered) return responder(res, 409, { error: 'Ya hay un WhatsApp vinculado' })
      if (estado !== 'qr') return responder(res, 503, { error: 'Todavía se está preparando la conexión; probá en unos segundos' })
      const { telefono } = await leerJson(req)
      const digitos = soloDigitos(telefono)
      if (digitos.length < 10) return responder(res, 400, { error: 'Ingresá el número completo con código de país (ej. 5491122334455)' })
      const codigo = await sock.requestPairingCode(digitos)
      codigoVinculacion = String(codigo || '').replace(/(.{4})(?=.)/, '$1-')
      console.log('[bridge] Código de vinculación generado para', digitos.slice(0, 4) + '…')
      return responder(res, 200, { codigo: codigoVinculacion })
    }
    if (req.method === 'POST' && req.url === '/logout') {
      try { await sock?.logout?.() } catch (_) {}
      await borrarSesion()
      estado = 'desconectado'
      numero = ''
      qrDataUrl = ''
      codigoVinculacion = ''
      setTimeout(conectar, 1000)
      return responder(res, 200, { ok: true })
    }
    return responder(res, 404, { error: 'no encontrado' })
  } catch (e) {
    return responder(res, 500, { error: e.message })
  }
})

let versionBaileys = '?'
try {
  const ruta = createRequire(import.meta.url).resolve('baileys/package.json')
  versionBaileys = JSON.parse(readFileSync(ruta, 'utf8')).version
} catch (_) {
  try { versionBaileys = JSON.parse(readFileSync(new URL('./node_modules/baileys/package.json', import.meta.url), 'utf8')).version } catch (_) {}
}
console.log('[bridge] Baileys', versionBaileys, '· Node', process.version)

servidor.listen(PUERTO_PUENTE, '127.0.0.1', () => {
  console.log(`[bridge] API interna en 127.0.0.1:${PUERTO_PUENTE} · envío ${ENVIO_HABILITADO ? 'habilitado' : 'deshabilitado'}`)
})

// ── Mantener despierto el plan gratis de Render ───────────────────────────
// El plan gratis se duerme tras 15 min sin tráfico entrante, y dormido no
// recibe WhatsApp. Pedir /health a la URL pública cada 10 min lo mantiene
// despierto (entra por el balanceador de Render como tráfico normal).
if (KEEPALIVE && URL_PUBLICA) {
  setInterval(() => {
    fetch(`${URL_PUBLICA}/health`).catch(() => {})
  }, 10 * 60 * 1000)
}

process.on('unhandledRejection', (e) => console.error('[bridge] Promesa rechazada:', e?.message || e))
conectar()
