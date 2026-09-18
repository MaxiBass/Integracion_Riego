/*
 * Estrategia de panel para la integración "Riego por Balance Hídrico".
 *
 * Construye el panel a partir de las entidades que publica la integración,
 * de modo que añadir o quitar una zona en las opciones se refleje sin tocar
 * el panel. Solo usa tarjetas nativas de Home Assistant: no depende de
 * mushroom, apexcharts ni mini-graph-card.
 *
 * Genera dos vistas complementarias:
 *   · Resumen — de un vistazo: qué va a regar, cuánta agua y por qué.
 *   · Detalle — una sección por zona con todos los números y los ajustes.
 *
 * Uso: crear un panel nuevo y, en su editor en modo YAML, poner
 *
 *     strategy:
 *       type: custom:riego
 *
 * Si una actualización de Home Assistant cambiara la API de estrategias,
 * en docs/DECISIONES.md está el YAML equivalente para pegarlo a mano.
 */

const DOMINIO = "riego";

// Sufijos reales de los entity_id, que HA deriva del `name` de cada
// descripción. No coinciden con la `key` interna: "deficit" produce
// `..._deficit_acumulado` y "kc" produce `..._kc_del_mes`.
const ORDEN_SISTEMA = [
  "et0_instantanea",
  "et0_acumulada_del_periodo",
  "et0_del_periodo_anterior",
  "lluvia_efectiva",
  "proximo_ciclo",
  "ultimo_ciclo",
];

const ORDEN_ZONA = [
  "estado",
  "deficit_acumulado",
  "falta_para_regar",
  "volumen_objetivo",
  "kc_del_mes",
  "caudal_aprendido",
  "litros_del_ultimo_ciclo",
  "litros_de_la_temporada",
  "ultimo_riego",
];

// Los number con pocos pasos se manejan bien a botones; superficie y techo
// tienen rangos amplios y se teclean mejor en una tarjeta "entities".
const NUMEROS_CON_BOTONES = ["umbral_de_riego", "coeficiente_de_ajuste"];

/** Entidades de la integración, agrupadas por dispositivo. */
function agrupar(hass) {
  const porDispositivo = new Map();
  const sueltas = [];

  for (const entrada of Object.values(hass.entities || {})) {
    if (entrada.platform !== DOMINIO) continue;
    if (entrada.disabled_by || entrada.hidden_by) continue;
    if (entrada.device_id) {
      if (!porDispositivo.has(entrada.device_id)) porDispositivo.set(entrada.device_id, []);
      porDispositivo.get(entrada.device_id).push(entrada.entity_id);
    } else {
      sueltas.push(entrada.entity_id);
    }
  }
  return { porDispositivo, sueltas };
}

function nombreDispositivo(hass, deviceId) {
  const d = (hass.devices || {})[deviceId] || {};
  return d.name_by_user || d.name || "Zona";
}

/** Ordena según una lista de sufijos; lo no listado va al final. */
function ordenar(entidades, orden) {
  const peso = (id) => {
    const indice = orden.findIndex((sufijo) => id.endsWith(`_${sufijo}`));
    return indice === -1 ? orden.length : indice;
  };
  return [...entidades].sort((a, b) => peso(a) - peso(b) || a.localeCompare(b));
}

/** Primera entidad cuyo entity_id acaba en `_<sufijo>`. */
function porSufijo(entidades, sufijo) {
  return entidades.find((e) => e.endsWith(`_${sufijo}`));
}

/** Nombre corto: el friendly_name incluye el del dispositivo por delante. */
function nombreCorto(hass, entityId, nombreDispositivo) {
  const completo = (hass.states[entityId] || {}).attributes?.friendly_name || entityId;
  if (nombreDispositivo && completo.startsWith(nombreDispositivo + " ")) {
    return completo.slice(nombreDispositivo.length + 1);
  }
  return completo;
}

/** Nombre de zona sin el prefijo "Zona ", para las etiquetas cortas. */
function etiquetaZona(nombre) {
  return nombre.replace(/^Zona\s+/i, "");
}

function numero(hass, entityId, porDefecto) {
  const valor = parseFloat((hass.states[entityId] || {}).state);
  return Number.isFinite(valor) ? valor : porDefecto;
}

const tarjeta = (entity, extra = {}) => ({ type: "tile", entity, ...extra });

// El tile de un switch usa la caracteristica "toggle". "switch-toggle" no
// existe y hace que HA pinte una tarjeta de error de configuracion.
const TOGGLE = [{ type: "toggle" }];
// "box" no es un estilo válido de numeric-input: los únicos son "buttons" y
// "slider". Con un valor inválido el tile se queda sin control utilizable.
const BOTONES = [{ type: "numeric-input", style: "buttons" }];
const LLENO = { columns: "full" };

const encabezado = (texto, icono, estilo = "title", badges) => {
  const c = { type: "heading", heading: texto, heading_style: estilo, icon: icono };
  if (badges && badges.length) {
    c.badges = badges.map((entity) => ({ type: "entity", entity }));
  }
  return c;
};

// ──────────────────────────── Vista Resumen ────────────────────────────

/*
 * Ojo con el ancho de las tarjetas: dentro de una sección la rejilla no es
 * de 12 columnas sino de 12 × column_span. Con column_span 3, "columns: 12"
 * ocupa un tercio del ancho y "columns: 4" solo un noveno.
 */
const COLS = 36;

function plantillaResumen(zonas) {
  const filas = zonas
    .map(({ nombre, entidades }) => {
      const e = (s) => porSufijo(entidades, s) || "";
      return `('${etiquetaZona(nombre).replace(/'/g, "")}','${e("estado")}',` +
        `'${e("deficit_acumulado")}','${e("volumen_objetivo")}','${e("bloqueada")}',` +
        `'${e("habilitada")}')`;
    })
    .join(",");

  return `{%- set zonas = [${filas}] -%}
{%- set ns = namespace(total=0) -%}
{%- for nom, est, def, vol, blo, hab in zonas -%}
{%- set ns.total = ns.total + states(vol) | int(0) -%}
{%- endfor -%}
{%- set prox = states('SENSOR_PROXIMO') -%}
{%- set dias = ['lunes','martes','miércoles','jueves','viernes','sábado','domingo'] -%}
{% if is_state('SWITCH_SIM','on') %}### 🧪 Modo simulación activo
No se enviará agua a las válvulas.
{% elif is_state('BINARY_APLAZADO','on') %}### 🌧️ Ciclo aplazado por lluvia prevista
El déficit se conserva para el próximo ciclo.
{% elif ns.total > 0 %}### 💧 {{ ns.total }} L previstos
{% else %}### 🌱 Sin riego pendiente
El déficit se está acumulando para el próximo ciclo.
{% endif %}
{% if prox not in ['unknown','unavailable','none','None'] -%}
**Próximo ciclo:** {{ dias[(prox | as_datetime | as_local).weekday()] }} {{ prox | as_timestamp | timestamp_custom('%d/%m a las %H:%M') }} · dentro de {{ ((prox | as_timestamp - now().timestamp()) / 3600) | round(1) }} h
{%- endif %}

| Zona | Estado | Déficit | Previsto |
|:--|:--|--:|--:|
{% for nom, est, def, vol, blo, hab in zonas -%}
| {{ nom }} | {{ states(est) }} | {{ states(def) }} mm | {{ states(vol) }} L |
{% endfor -%}
| **Total** | | | **{{ ns.total }} L** |

ET₀ periodo anterior **{{ states('SENSOR_ET0_ANTERIOR') }} mm** ·
acumulada **{{ states('SENSOR_ET0_ACUM') }} mm** ·
lluvia efectiva **{{ states('SENSOR_LLUVIA') }} mm**
{% for nom, est, def, vol, blo, hab in zonas -%}
{%- if blo and is_state(blo,'on') %}
⛔ {{ nom }} bloqueada — el riego se salta y el déficit se conserva
{% endif -%}
{%- if hab and is_state(hab,'off') %}
⏸️ {{ nom }} deshabilitada
{% endif -%}
{%- endfor %}`;
}

function plantillaUltimoRiego(zonas, sensorCiclo) {
  const filas = zonas
    .map(({ nombre, entidades }) => {
      const litros = porSufijo(entidades, "litros_del_ultimo_ciclo") || "";
      const cuando = porSufijo(entidades, "ultimo_riego") || "";
      return `('${etiquetaZona(nombre).replace(/'/g, "")}','${litros}','${cuando}')`;
    })
    .join(",");

  return `{%- set zonas = [${filas}] -%}
{%- set ciclo = states('${sensorCiclo}') -%}
{%- set dias = ['lunes','martes','miércoles','jueves','viernes','sábado','domingo'] -%}
{%- set ns = namespace(total=0, regadas=0) -%}
{%- for nom, lit, cua in zonas -%}
{%- set dentro = ciclo | as_timestamp(0) > 0 and states(cua) | as_timestamp(0) > 0 and (states(cua) | as_timestamp - ciclo | as_timestamp) | abs < 3600 -%}
{%- if dentro and states(lit) | float(0) > 0 -%}
{%- set ns.total = ns.total + states(lit) | float(0) -%}
{%- set ns.regadas = ns.regadas + 1 -%}
{%- endif -%}
{%- endfor -%}
{% if ns.regadas == 0 %}### 🌙 Sin riego en el último ciclo
{% else %}### 🚿 {{ ns.total | round | int }} L aplicados en {{ ns.regadas }} zona{{ 's' if ns.regadas > 1 }}
{% endif %}
{% if ciclo | as_timestamp(0) > 0 -%}
{{ dias[(ciclo | as_datetime | as_local).weekday()] }} {{ ciclo | as_timestamp | timestamp_custom('%d/%m a las %H:%M') }} · hace {{ ((now().timestamp() - ciclo | as_timestamp) / 3600) | round(1) }} h
{%- endif %}

| Zona | Aplicado | Hora |
|:--|--:|--:|
{% for nom, lit, cua in zonas -%}
{%- set dentro = ciclo | as_timestamp(0) > 0 and states(cua) | as_timestamp(0) > 0 and (states(cua) | as_timestamp - ciclo | as_timestamp) | abs < 3600 -%}
{%- if dentro and states(lit) | float(0) > 0 -%}
| {{ nom }} | {{ states(lit) | round | int }} L | {{ states(cua) | as_timestamp | timestamp_custom('%H:%M') }} |
{% else -%}
| {{ nom }} | — | |
{% endif -%}
{% endfor -%}
{% if ns.regadas > 0 %}| **Total** | **{{ ns.total | round | int }} L** | |{% endif %}`;
}

function vistaResumen(hass, sistema, zonas) {
  const s = (sufijo) => porSufijo(sistema, sufijo) || "";
  const contenido = plantillaResumen(zonas)
    .replace("SENSOR_PROXIMO", s("proximo_ciclo"))
    .replace("SWITCH_SIM", s("simulacion"))
    .replace("BINARY_APLAZADO", s("aplazado_por_lluvia_prevista"))
    .replace("SENSOR_ET0_ANTERIOR", s("et0_del_periodo_anterior"))
    .replace("SENSOR_ET0_ACUM", s("et0_acumulada_del_periodo"))
    .replace("SENSOR_LLUVIA", s("lluvia_efectiva"));

  const badges = [
    s("proximo_ciclo"),
    s("aplazado_por_lluvia_prevista"),
    s("simulacion"),
  ].filter(Boolean);

  const secciones = [
    {
      type: "grid",
      column_span: 3,
      cards: [
        encabezado("Riego por balance hídrico", "mdi:sprinkler-variant", "title", badges),
        { type: "markdown", grid_options: LLENO, content: contenido },
      ],
    },
  ];

  const sensorCiclo = s("ultimo_ciclo");
  if (sensorCiclo && zonas.length) {
    secciones.push({
      type: "grid",
      column_span: 3,
      cards: [
        encabezado("Último riego", "mdi:history", "subtitle", [sensorCiclo]),
        {
          type: "markdown",
          grid_options: LLENO,
          content: plantillaUltimoRiego(zonas, sensorCiclo),
        },
      ],
    });
  }

  // Medidores: volumen previsto sobre el techo de seguridad de cada zona.
  const medidores = [];
  const faltas = [];
  for (const { nombre, entidades } of zonas) {
    const volumen = porSufijo(entidades, "volumen_objetivo");
    const techo = porSufijo(entidades, "techo_de_seguridad");
    const falta = porSufijo(entidades, "falta_para_regar");
    const ancho = { columns: Math.max(Math.floor(COLS / Math.max(zonas.length, 1)), 6) };
    if (volumen) {
      const maximo = techo ? numero(hass, techo, 1000) : 1000;
      medidores.push({
        type: "gauge",
        entity: volumen,
        name: etiquetaZona(nombre),
        unit: "L",
        min: 0,
        max: maximo,
        needle: true,
        severity: { green: 0, yellow: Math.round(maximo * 0.7), red: Math.round(maximo * 0.9) },
        grid_options: ancho,
      });
    }
    if (falta) {
      faltas.push(tarjeta(falta, { name: `${etiquetaZona(nombre)} · falta`, grid_options: ancho }));
    }
  }
  if (medidores.length) {
    secciones.push({
      type: "grid",
      column_span: 3,
      cards: [
        encabezado("Previsto para el próximo ciclo", "mdi:water-outline", "subtitle"),
        ...medidores,
        ...faltas,
      ],
    });
  }

  // Agua aplicada: "litros de la temporada" es total_increasing, así que su
  // estadística de cambio por día sobrevive a la purga del histórico.
  const temporada = zonas
    .map(({ nombre, entidades }) => {
      const e = porSufijo(entidades, "litros_de_la_temporada");
      return e ? { entity: e, name: etiquetaZona(nombre) } : null;
    })
    .filter(Boolean);
  if (temporada.length) {
    secciones.push({
      type: "grid",
      column_span: 3,
      cards: [
        encabezado("Agua aplicada por día", "mdi:chart-bar", "subtitle"),
        {
          type: "statistics-graph",
          grid_options: LLENO,
          period: "day",
          stat_types: ["change"],
          chart_type: "bar",
          days_to_show: 14,
          entities: temporada,
        },
        {
          type: "statistics-graph",
          grid_options: LLENO,
          title: "Por mes",
          period: "month",
          stat_types: ["change"],
          chart_type: "bar",
          days_to_show: 365,
          entities: temporada,
        },
      ],
    });
  }

  const et0Anterior = s("et0_del_periodo_anterior");
  const et0Ahora = s("et0_instantanea");
  const lluvia = s("lluvia_efectiva");
  const demanda = [encabezado("Demanda y lluvia", "mdi:weather-sunny", "subtitle")];
  if (et0Anterior) {
    demanda.push({
      type: "statistics-graph",
      grid_options: { columns: COLS / 2 },
      title: "ET₀ diaria",
      period: "day",
      stat_types: ["max"],
      chart_type: "bar",
      days_to_show: 30,
      entities: [{ entity: et0Anterior, name: "ET₀ del día" }],
    });
  }
  if (lluvia) {
    demanda.push({
      type: "statistics-graph",
      grid_options: { columns: COLS / 2 },
      title: "Lluvia efectiva",
      period: "day",
      stat_types: ["max"],
      chart_type: "bar",
      days_to_show: 30,
      entities: [{ entity: lluvia, name: "Lluvia" }],
    });
  }
  if (et0Ahora) {
    demanda.push({
      type: "history-graph",
      grid_options: LLENO,
      hours_to_show: 48,
      entities: [{ entity: et0Ahora, name: "ET₀ instantánea" }],
    });
  }
  if (demanda.length > 1) {
    secciones.push({ type: "grid", column_span: 3, cards: demanda });
  }

  return {
    title: "Resumen",
    path: "resumen",
    icon: "mdi:view-dashboard-outline",
    type: "sections",
    max_columns: 3,
    sections: secciones,
  };
}

// ──────────────────────────── Vista Detalle ────────────────────────────

function seccionSistema(hass, entidades) {
  const sensores = ordenar(
    entidades.filter((e) => e.startsWith("sensor.")),
    ORDEN_SISTEMA
  );
  const interruptores = entidades.filter((e) => e.startsWith("switch."));
  const binarios = entidades.filter((e) => e.startsWith("binary_sensor."));

  const n = (e) => nombreCorto(hass, e, "Balance Hídrico");
  const cards = [
    encabezado("Balance hídrico", "mdi:water-sync"),
    ...sensores.map((e) => tarjeta(e, { name: n(e) })),
    ...binarios.map((e) => tarjeta(e, { name: n(e) })),
    ...interruptores.map((e) => tarjeta(e, { name: n(e), features: TOGGLE })),
  ];

  const acumulada = porSufijo(entidades, "et0_acumulada_del_periodo");
  const lluvia = porSufijo(entidades, "lluvia_efectiva");
  const series = [];
  if (acumulada) series.push({ entity: acumulada, name: "ET₀ acumulada" });
  if (lluvia) series.push({ entity: lluvia, name: "Lluvia efectiva" });
  if (series.length) {
    cards.push({
      type: "history-graph",
      grid_options: LLENO,
      hours_to_show: 168,
      entities: series,
    });
  }

  return { type: "grid", cards };
}

function seccionZona(hass, nombre, entidades) {
  const sensores = ordenar(
    entidades.filter((e) => e.startsWith("sensor.")),
    ORDEN_ZONA
  );
  const binarios = entidades.filter((e) => e.startsWith("binary_sensor."));
  const interruptores = entidades.filter((e) => e.startsWith("switch."));
  const numeros = entidades.filter((e) => e.startsWith("number."));

  const n = (e) => nombreCorto(hass, e, nombre);
  const tarjetas = [
    encabezado(nombre, "mdi:sprinkler-variant"),
    ...interruptores.map((e) => tarjeta(e, { name: n(e), features: TOGGLE })),
    ...binarios.map((e) => tarjeta(e, { name: n(e) })),
    ...sensores.map((e) => tarjeta(e, { name: n(e) })),
  ];

  if (numeros.length) {
    tarjetas.push(encabezado("Ajustes", "mdi:tune", "subtitle"));
    const conBotones = numeros.filter((e) =>
      NUMEROS_CON_BOTONES.some((sufijo) => e.endsWith(`_${sufijo}`))
    );
    const tecleados = numeros.filter((e) => !conBotones.includes(e));
    for (const e of conBotones) {
      tarjetas.push(tarjeta(e, { name: n(e), features: BOTONES }));
    }
    if (tecleados.length) {
      tarjetas.push({
        type: "entities",
        grid_options: LLENO,
        entities: tecleados.map((e) => ({ entity: e, name: n(e) })),
      });
    }
  }

  const temporada = porSufijo(entidades, "litros_de_la_temporada");
  const deficit = porSufijo(entidades, "deficit_acumulado");
  if (temporada || deficit) {
    tarjetas.push(encabezado("Histórico", "mdi:chart-line", "subtitle"));
  }
  if (temporada) {
    tarjetas.push({
      type: "statistics-graph",
      grid_options: LLENO,
      title: "Litros por día",
      period: "day",
      stat_types: ["change"],
      chart_type: "bar",
      days_to_show: 30,
      entities: [{ entity: temporada, name: etiquetaZona(nombre) }],
    });
  }
  if (deficit) {
    tarjetas.push({
      type: "history-graph",
      grid_options: LLENO,
      hours_to_show: 168,
      entities: [{ entity: deficit, name: "Déficit — 7 días" }],
    });
  }

  return { type: "grid", cards: tarjetas };
}

class EstrategiaRiego extends HTMLElement {
  static async generate(_config, hass) {
    const { porDispositivo, sueltas } = agrupar(hass);

    if (porDispositivo.size === 0 && sueltas.length === 0) {
      return {
        views: [
          {
            title: "Riego",
            cards: [
              {
                type: "markdown",
                content:
                  "### Riego\nNo se han encontrado entidades de la integración.\n\n" +
                  "Comprueba que **Riego por Balance Hídrico** esté configurada en " +
                  "*Ajustes → Dispositivos y servicios*.",
              },
            ],
          },
        ],
      };
    }

    let sistema = [...sueltas];
    const zonas = [];

    for (const [deviceId, entidades] of porDispositivo) {
      const nombre = nombreDispositivo(hass, deviceId);
      if (nombre.toLowerCase().startsWith("zona")) {
        zonas.push({ nombre, entidades });
      } else {
        sistema = sistema.concat(entidades);
      }
    }

    zonas.sort((a, b) => a.nombre.localeCompare(b.nombre));

    const secciones = [];
    if (sistema.length) secciones.push(seccionSistema(hass, sistema));
    for (const { nombre, entidades } of zonas) {
      secciones.push(seccionZona(hass, nombre, entidades));
    }

    const detalle = {
      title: "Detalle",
      path: "detalle",
      icon: "mdi:format-list-bulleted",
      type: "sections",
      max_columns: 4,
      sections: secciones,
    };

    return { views: [vistaResumen(hass, sistema, zonas), detalle] };
  }
}

// Un mismo constructor no puede registrarse con dos nombres: el segundo
// define() lanza "this constructor has already been used with this registry"
// y aborta el módulo. Cada alias necesita su propia subclase.
for (const nombre of ["ll-strategy-dashboard-riego", "ll-strategy-dashboard-riego-strategy"]) {
  if (!customElements.get(nombre)) {
    customElements.define(nombre, class extends EstrategiaRiego {});
  }
}

console.info("%c RIEGO %c estrategia de panel cargada ", "background:#2e7d32;color:#fff", "");
