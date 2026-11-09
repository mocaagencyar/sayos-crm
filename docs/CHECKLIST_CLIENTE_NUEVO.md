# Checklist para dar de alta un cliente nuevo

Guía rápida de qué pedirle al cliente y cómo clonar este repo base. El detalle
técnico de deploy (Render, Postgres, variables completas) está en
[`DEPLOY_CLIENTES.md`](DEPLOY_CLIENTES.md) — este archivo es el paso previo:
qué información juntar antes de ponerse a deployar.

## 1. Cuestionario para el cliente

### Negocio (`config/business.yaml` y `prompts.yaml`)
- [ ] Nombre del negocio
- [ ] Qué vende / a quién / qué lo diferencia
- [ ] Horario de atención
- [ ] Web y email de contacto
- [ ] Servicios o paquetes, con precios (o si prefiere no compartir precios por WhatsApp)
- [ ] Perfil de cliente ideal — a quién SÍ conviene atender, a quién no
- [ ] Objeciones típicas y cómo las responde el negocio
- [ ] Link de agenda (Calendly, Google Calendar) para que Max agende reuniones
- [ ] Archivos de apoyo si tiene (catálogo, FAQ, menú, precios) → van a `knowledge/`

### WhatsApp
- [ ] ¿Tiene Meta Business Manager verificado? (si no, hay que crearlo — la verificación de Meta puede tardar días, arrancar esto temprano)
- [ ] ¿Quiere mantener su WhatsApp Business App actual en el mismo número (coexistencia)? Si sí, el setup es más largo — avisarlo antes
- [ ] Alternativa rápida sin esperar a Meta: Whapi.cloud (no es la API oficial, pero arranca en minutos)

### Telegram
- [ ] ¿Quién recibe los avisos de leads/mensajes nuevos?
- [ ] Esa persona crea un bot con `@BotFather` (o se lo creás vos) → token
- [ ] Chat ID al que avisar (grupo o chat directo)

### Dashboard
- [ ] Usuario y contraseña que quiere usar para loguearse
- [ ] Marca: nombre a mostrar, color principal (hex), logo (archivo PNG o URL pública)

## 2. Clonar el repo base

### Caso A — repo nuevo en la misma cuenta/org de GitHub que ya tengo conectada
Lo hago directo, sin pasos de tu lado.

### Caso B — repo en otra cuenta/org de GitHub
1. Creás vos el repo vacío en esa cuenta (sin README/gitignore/license — vacío de verdad).
2. Si esa cuenta no tiene instalada la GitHub App de Claude: entrás a
   [claude.ai/connect-github](https://claude.ai/connect-github), agregás esa cuenta/org,
   y le das acceso al repo nuevo (podés limitarlo a ese repo solo).
3. Me pasás el link del repo vacío y yo clono la base ahí.

Si alguna vez lo necesitás hacer vos a mano, sin pasar por acá:
```bash
git clone https://github.com/MarcosGrowth/estructura-crm-propio.git nombre-cliente
cd nombre-cliente
git remote set-url origin https://github.com/CUENTA-DESTINO/repo-nuevo-cliente.git
git push -u origin main
```

## 3. Después de clonar

Seguir [`DEPLOY_CLIENTES.md`](DEPLOY_CLIENTES.md) para el deploy técnico completo
(Render, PostgreSQL, variables de entorno, webhook). Resumen:

1. Servicio web nuevo en Render, conectado al repo del cliente.
2. Base PostgreSQL nueva (Render o Supabase) — nunca SQLite en producción.
3. Variables de entorno: credenciales de WhatsApp/Anthropic + `TELEGRAM_*` + `BRAND_*`.
4. Completar `config/business.yaml` y `config/prompts.yaml` con lo que juntaste en el paso 1.
5. Configurar el webhook del proveedor de WhatsApp apuntando a la URL de Render.
6. Probar de punta a punta: mandar un mensaje de prueba → aparece en **Bandeja** →
   califica → llega el aviso a Telegram → el dashboard muestra la marca correcta del cliente.
