/*
 * Estrategia de panel para la integración "Riego por Balance Hídrico".
 *
 * Construye el panel a partir de las entidades que publica la integración,
 * de modo que añadir o quitar una zona en las opciones se refleje sin tocar
 * el panel. Solo usa tarjetas nativas de Home Assistant: no depende de
 * mushroom, apexcharts ni mini-graph-card.
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

const ORDEN_SISTEMA = [
  "et0_instantanea",
  "et0_acumulada",
  "et0_periodo_anterior",
  "lluvia_efectiva",
  "proximo_ciclo",
  "ultimo_ciclo",
];

const ORDEN_ZONA = [
  "estado",
  "deficit",
  "falta_para_regar",
  "volumen_objetivo",
  "litros_hoy",
  "litros_temporada",
  "caudal_aprendido",
  "kc",
  "ultimo_riego",
];

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

const tarjeta = (entity, extra = {}) => ({ type: "tile", entity, ...extra });

function seccionSistema(hass, entidades) {
  const sensores = ordenar(
    entidades.filter((e) => e.startsWith("sensor.")),
    ORDEN_SISTEMA
  );
  const interruptores = entidades.filter((e) => e.startsWith("switch."));
  const binarios = entidades.filter((e) => e.startsWith("binary_sensor."));

  return {
    type: "grid",
    cards: [
      { type: "heading", heading: "Balance hídrico", heading_style: "title", icon: "mdi:water-sync" },
      ...sensores.map((e) => tarjeta(e)),
      ...binarios.map((e) => tarjeta(e)),
      ...interruptores.map((e) => tarjeta(e, { features: [{ type: "switch-toggle" }] })),
    ],
  };
}

function seccionZona(hass, nombre, entidades) {
  const sensores = ordenar(
    entidades.filter((e) => e.startsWith("sensor.")),
    ORDEN_ZONA
  );
  const binarios = entidades.filter((e) => e.startsWith("binary_sensor."));
  const interruptores = entidades.filter((e) => e.startsWith("switch."));
  const numeros = entidades.filter((e) => e.startsWith("number."));
  const deficit = sensores.find((e) => e.endsWith("_deficit"));

  const tarjetas = [
    { type: "heading", heading: nombre, heading_style: "title", icon: "mdi:sprinkler-variant" },
    ...interruptores.map((e) => tarjeta(e, { features: [{ type: "switch-toggle" }] })),
    ...binarios.map((e) => tarjeta(e)),
    ...sensores.map((e) => tarjeta(e)),
  ];

  if (numeros.length) {
    tarjetas.push({ type: "heading", heading: "Ajustes", heading_style: "subtitle" });
    tarjetas.push({
      type: "entities",
      entities: numeros,
    });
  }

  if (deficit) {
    tarjetas.push({
      type: "history-graph",
      hours_to_show: 168,
      entities: [{ entity: deficit, name: "Déficit — 7 días" }],
      grid_options: { columns: "full" },
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

    const secciones = [];
    const zonas = [];

    for (const [deviceId, entidades] of porDispositivo) {
      const nombre = nombreDispositivo(hass, deviceId);
      if (nombre.toLowerCase().startsWith("zona")) {
        zonas.push([nombre, entidades]);
      } else {
        secciones.push(seccionSistema(hass, entidades));
      }
    }

    if (sueltas.length) secciones.push(seccionSistema(hass, sueltas));

    zonas.sort((a, b) => a[0].localeCompare(b[0]));
    for (const [nombre, entidades] of zonas) {
      secciones.push(seccionZona(hass, nombre, entidades));
    }

    return {
      views: [
        {
          title: "Riego",
          path: "riego",
          icon: "mdi:water",
          type: "sections",
          max_columns: 4,
          sections: secciones,
        },
      ],
    };
  }
}

for (const nombre of ["ll-strategy-dashboard-riego", "ll-strategy-dashboard-riego-strategy"]) {
  if (!customElements.get(nombre)) customElements.define(nombre, EstrategiaRiego);
}

console.info("%c RIEGO %c estrategia de panel cargada ", "background:#2e7d32;color:#fff", "");
