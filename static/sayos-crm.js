/* ============================================================
   sayos-crm.js — Conexión de la landing con el CRM de Sayos
   ------------------------------------------------------------
   Hace dos cosas, sin tocar el código de la landing:

   1) Registra en el CRM cada consulta del formulario, un instante
      antes de que la persona pase a WhatsApp.
   2) Lee el stock real del CRM: si una heladera se vendió y se
      marcó como ganada, deja de mostrarse en la landing.

   Se engancha "desde afuera": escucha los clics dentro del
   diálogo de consulta y lee las tarjetas por su atributo
   data-reserve. Cubre las dos formas de disparar la consulta
   (enlace "Seguir por WhatsApp", botón "Copiar") y además el
   envío de formulario, por si una versión futura vuelve a usarlo.

   Instalación: copiar este archivo junto al index.html y agregar
   antes de </body>:
       <script src="sayos-crm.js" defer></script>

   Si el CRM no responde, la landing funciona igual: nunca frena
   el paso a WhatsApp.
   ============================================================ */
(function () {
  "use strict";

  var CRM = "https://sayos-crm.onrender.com";
  var CAMPANIA = "Black Sayos";

  // Medición. Se inyecta desde acá para no tocar el código de la landing.
  var GTM = ["GTM-N3QKFSHC"];        // contenedores de Google Tag Manager
  var META_PIXEL = "3701207983381610";
  // La copia de pruebas no mide: ensuciaría los datos de la campaña.
  var MIDE = !/\.pages\.dev$/i.test(location.hostname);

  var ultimoModelo = "";   // modelo de la tarjeta en la que se hizo clic
  var yaEnviado = {};      // evita mandar dos veces la misma consulta

  /* ---------- 0. Medición (GTM + píxel de Meta) ---------- */
  function cargarScript(src) {
    var t = document.createElement("script");
    t.async = true; t.src = src;
    document.head.appendChild(t);
  }

  function cargarTracking() {
    if (!MIDE) return;
    window.dataLayer = window.dataLayer || [];

    GTM.forEach(function (id) {
      if (!id) return;
      // Si la landing ya trae el contenedor, no lo duplicamos
      if (document.querySelector('script[src*="' + id + '"]')) return;
      window.dataLayer.push({ "gtm.start": new Date().getTime(), event: "gtm.js" });
      cargarScript("https://www.googletagmanager.com/gtm.js?id=" + id);
    });

    if (META_PIXEL && !window.fbq) {
      var n = window.fbq = function () {
        n.callMethod ? n.callMethod.apply(n, arguments) : n.queue.push(arguments);
      };
      if (!window._fbq) window._fbq = n;
      n.push = n; n.loaded = true; n.version = "2.0"; n.queue = [];
      cargarScript("https://connect.facebook.net/en_US/fbevents.js");
      window.fbq("init", META_PIXEL);
      window.fbq("track", "PageView");
    }
  }

  // Avisa a Meta que esta consulta es un lead, en el mismo momento en que
  // se registra en el CRM. Sin esto, Meta no puede optimizar la campaña.
  function avisarLead(datos) {
    if (!MIDE) return;
    try {
      if (window.fbq) window.fbq("track", "Lead", {
        content_name: datos.producto || "Consulta general",
        content_category: datos.rubro || "",
        source: CAMPANIA
      });
      if (window.dataLayer) window.dataLayer.push({
        event: "crm_lead_registrado",
        modelo: datos.modelo || "",
        rubro: datos.rubro || ""
      });
    } catch (_) {}
  }

  /* ---------- helpers ---------- */
  function texto(sel) {
    var el = document.querySelector(sel);
    return el ? String(el.textContent || "").replace(/\s+/g, " ").trim() : "";
  }
  function param(nombre) {
    try { return new URLSearchParams(location.search).get(nombre) || ""; }
    catch (_) { return ""; }
  }
  function valor(form, campo) {
    var el = form && form.querySelector("[name=" + campo + "]");
    return el ? String(el.value || "").trim() : "";
  }

  /* ---------- 1. Registrar la consulta ---------- */

  // Guardamos el modelo de la tarjeta en la que se hizo clic
  document.addEventListener("click", function (e) {
    if (!e.target || !e.target.closest) return;
    var b = e.target.closest("[data-reserve]");
    if (b) { ultimoModelo = b.getAttribute("data-reserve") || ""; return; }
    // Los accesos sueltos (flotante, cierre) abren una consulta general:
    // sin esto el lead quedaría etiquetado con el último modelo mirado.
    if (e.target.closest("[data-wa]")) ultimoModelo = "";
  }, true);

  // Campo trampa: lo completan los bots, las personas no lo ven
  function ponerTrampa(form) {
    if (!form || form.querySelector("[name=web]")) return;
    var t = document.createElement("input");
    t.name = "web"; t.tabIndex = -1; t.setAttribute("autocomplete", "off");
    t.setAttribute("aria-hidden", "true");
    t.style.cssText = "position:absolute;left:-9999px;width:1px;height:1px;opacity:0";
    form.appendChild(t);
  }

  function registrar(form) {
    if (!form) return;
    var nombre = valor(form, "nombre");
    var rubro = valor(form, "rubro");
    var local = valor(form, "local");
    var localidad = valor(form, "localidad");

    // Solo registramos consultas completas: así no entran medias cargas
    // cuando la landing rechaza el formulario por un campo que falta.
    if (!nombre || !rubro || !local || !localidad) return;

    var firma = [nombre, local, localidad, ultimoModelo].join("|").toLowerCase();
    if (yaEnviado[firma]) return;
    yaEnviado[firma] = true;
    setTimeout(function () { delete yaEnviado[firma]; }, 60000);

    var producto = texto("#dlg-model");
    var cuerpo = JSON.stringify({
      campania: CAMPANIA,
      utm_source: param("utm_source"),
      utm_campaign: param("utm_campaign"),
      nombre: nombre,
      local: local,
      rubro: rubro,
      localidad: localidad,
      modelo: ultimoModelo,
      producto: producto,
      web: valor(form, "web"),
      mensaje: "Consulta desde la landing" + (producto ? ": " + producto : "")
    });

    avisarLead({ producto: producto, rubro: rubro, modelo: ultimoModelo });

    var url = CRM + "/api/public/lead";
    try {
      // sendBeacon sobrevive al cambio de pestaña hacia WhatsApp
      if (!(navigator.sendBeacon && navigator.sendBeacon(url, cuerpo))) {
        fetch(url, { method: "POST", body: cuerpo, keepalive: true }).catch(function () {});
      }
    } catch (_) {
      try { fetch(url, { method: "POST", body: cuerpo, keepalive: true }).catch(function () {}); } catch (__) {}
    }
  }

  // ¿El clic es el que lleva la consulta a WhatsApp?
  function esDisparador(el) {
    if (!el || !el.closest) return false;
    // Solo dentro del diálogo de consulta o del propio formulario:
    // los botones sueltos de WhatsApp de la página no traen datos.
    if (!el.closest("dialog") && !el.closest("form")) return false;
    if (el.closest("[id*=close]")) return false;
    var a = el.closest("a");
    if (a && /wa\.me|whatsapp/i.test(a.getAttribute("href") || "")) return true;
    if (el.closest(".btn.wa, a.wa, [data-wa]")) return true;
    if (el.closest("[id*=copy], [class*=copy]")) return true;
    var b = el.closest("button");
    if (b && b.type === "submit") return true;
    return false;
  }

  document.addEventListener("click", function (e) {
    if (!esDisparador(e.target)) return;
    var form = (e.target.closest("form")) ||
               (e.target.closest("dialog") || document).querySelector("form") ||
               document.querySelector("#form");
    registrar(form);
  }, true);

  // Por si una versión futura vuelve a usar el envío de formulario
  document.addEventListener("submit", function (e) {
    var f = e.target;
    if (f && f.querySelector && f.querySelector("[name=nombre]")) registrar(f);
  }, true);

  /* ---------- 2. Stock real desde el CRM ---------- */

  function tarjetaDe(modelo) {
    var b = document.querySelector('[data-reserve="' + modelo + '"]');
    return b ? (b.closest(".card") || b.closest("article")) : null;
  }

  function aplicarStock(modelos) {
    if (!Array.isArray(modelos) || !modelos.length) return;
    var total = 0, visibles = 0, enCrm = {};

    modelos.forEach(function (m) {
      enCrm[m.id] = true;
      var card = tarjetaDe(m.id);
      if (!card) return;                        // modelo que la landing no muestra
      var u = Number(m.unidades) || 0;
      if (u <= 0) { card.style.display = "none"; return; }

      total += u; visibles++;
      var badge = card.querySelector(".badge");
      if (badge) {
        badge.textContent = u === 1 ? "Última unidad" : "Quedan " + u;
        badge.classList.toggle("last", u === 1);
      }
    });

    // Modelos que la landing muestra pero el CRM ya no tiene: se ocultan
    Array.prototype.forEach.call(document.querySelectorAll("[data-reserve]"), function (b) {
      if (enCrm[b.getAttribute("data-reserve")]) return;
      var card = b.closest(".card") || b.closest("article");
      if (card) card.style.display = "none";
    });

    var cont = document.getElementById("stock-total");
    if (cont) {
      cont.textContent = total === 0 ? "Stock agotado"
        : total === 1 ? "Última unidad en stock"
        : total + " unidades en stock";
    }

    var grid = document.getElementById("grid");
    if (!visibles && grid && !document.getElementById("sin-stock")) {
      var p = document.createElement("p");
      p.id = "sin-stock";
      p.style.cssText = "grid-column:1/-1;text-align:center;padding:40px 0";
      p.textContent = "Se agotó el stock de la promo. Escribinos y te avisamos cuando ingresen más unidades.";
      grid.appendChild(p);
    }
  }

  function leerStock() {
    // Si la landing ya sincroniza su propio stock contra el CRM, no nos
    // metemos: ella sabe manejar colores agotados y tarjetas agotadas.
    if (window.SAYOS_STOCK_PROPIO) return;
    fetch(CRM + "/api/public/stock", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.modelos) aplicarStock(d.modelos); })
      .catch(function () {});   // CRM caído: la landing queda con su stock propio
  }

  /* ---------- arranque ---------- */
  function iniciar() {
    cargarTracking();
    var campo = document.querySelector("[name=nombre]");
    ponerTrampa(campo ? campo.form : document.querySelector("#form"));
    leerStock();
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", iniciar);
  } else { iniciar(); }
})();
