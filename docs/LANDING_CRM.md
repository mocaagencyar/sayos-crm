# Landing ↔ CRM: consultas, stock y ventas

La landing y el CRM comparten dos datos: las **consultas** (landing → CRM) y el **stock** (CRM → landing).

## Cómo funciona

1. **Consulta.** Cuando alguien completa el formulario de una heladera y toca «Seguir por WhatsApp», la landing manda los datos al CRM (`POST /api/public/lead`) y abre WhatsApp. El envío no frena el paso a WhatsApp: si el CRM no responde, la persona llega igual.
2. **Lead.** La consulta aparece en el CRM como lead **Nuevo**, con nombre, local, rubro, localidad, modelo consultado y origen (campaña + `utm_source`). Como todavía no se conoce su número, figura como «Landing · sin WhatsApp cargado»; el botón **Cargar WhatsApp** lo completa (si ese número ya existe en el CRM, los dos contactos se fusionan).
3. **Seguimiento manual.** El equipo mueve la tarjeta de etapa a mano (arrastrando o con los botones).
4. **Venta.** Al tocar **✓ Ganado** se abre «Registrar venta»: se elige la heladera vendida y se descuenta una unidad. «Reabrir» anula la venta y devuelve la unidad.
5. **Stock en la landing.** La landing lee `GET /api/public/stock` al cargar. Los modelos sin unidades dejan de mostrarse y el contador «Quedan N» se actualiza solo.

## Dónde se ve

- **Resumen → Período:** Hoy, Ayer, Últimos 7 días, Este mes, Mes pasado, Todo o Personalizado. Debajo, el **Registro de consultas del período**.
- **Reportes:** embudo y origen de las consultas del mismo período. **Acciones → Exportar leads** baja todo a CSV.
- **Stock y ventas:** unidades por modelo y terminación (botones − / +, agregar, quitar) y lista de ventas.

## Configuración

- En la landing (`index.html`): `const CRM = "https://sayos-crm.onrender.com"` y `const CAMPANIA = "Black Sayos"`. El array `STOCK` queda como respaldo si el CRM no responde.
- En Render: `LANDING_ORIGINS` con el dominio de la landing (ej. `https://black.sayos.com.ar`). Con `*` acepta consultas de cualquier sitio.
- El stock inicial sale de `config/stock_inicial.yaml` y se carga una sola vez; después se administra desde el CRM.

## Límites

- La landing tiene que estar publicada en un dominio propio (hosting, WordPress, Render…). Dentro de una vista previa de claude.ai el navegador bloquea las llamadas al CRM y la página usa el stock de respaldo.
- Los botones generales de WhatsApp (flotante, «Hablar con ventas») no piden datos, así que no generan lead: solo el formulario de cada heladera.
- Protección contra abuso: 20 consultas por hora por IP, campo trampa para bots y tamaño máximo por campo.
