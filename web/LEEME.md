# Sitio público (Cloudflare Pages)

Esta carpeta es lo que se publica en el proyecto `sayosinstalaciones` de
Cloudflare Pages. Está conectada por Git: un push a `main` republica el sitio.

    index.html              copia de la landing (así estaba publicado)
    blacksayos/index.html   la landing Black Sayos
    blacksayos/img,clients,fonts,video

La landing llama al conector del CRM con una sola línea antes de `</body>`:

    <script src="https://sayos-crm.onrender.com/landing/sayos-crm.js" defer></script>

El conector vive en el CRM (`static/sayos-crm.js`), no acá: si hay que
corregirlo, se corrige allá y esta carpeta no se toca.

Configuración en Cloudflare: Root directory `web`, sin comando de build,
Build output directory `/`.
