/*
 * Ejecuta la estrategia de panel contra un `hass` sintético con los mismos
 * entity_id que produce la integración, y comprueba el resultado.
 *
 *     node tests/test_estrategia.mjs
 *
 * Existe porque los fallos de esta parte no los ve el panel: una tarjeta con
 * una opción inválida (p. ej. `style: "box"`, que no existe) se pinta sin
 * error visible pero deja el control inservible.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";

const aqui = dirname(fileURLToPath(import.meta.url));
const fuente = readFileSync(
  join(aqui, "..", "custom_components", "riego", "frontend", "riego-strategy.js"),
  "utf8"
);

// ── Carga del módulo con los mínimos del navegador ──────────────────────
let Estrategia = null;
const registro = new Map();
const contexto = {
  HTMLElement: class {},
  customElements: {
    get: (n) => registro.get(n),
    define: (n, c) => {
      registro.set(n, c);
      Estrategia ??= c;
    },
  },
  console: { info: () => {} },
};
vm.createContext(contexto);
vm.runInContext(fuente, contexto);

assert.ok(Estrategia, "la estrategia no se registró");
assert.equal(registro.size, 2, "deben registrarse los dos alias");
assert.notEqual(
  registro.get("ll-strategy-dashboard-riego"),
  registro.get("ll-strategy-dashboard-riego-strategy"),
  "cada alias necesita su propia subclase o define() lanza"
);

// ── hass sintético ──────────────────────────────────────────────────────
const SISTEMA = [
  "sensor.balance_hidrico_et0_instantanea",
  "sensor.balance_hidrico_et0_acumulada_del_periodo",
  "sensor.balance_hidrico_et0_del_periodo_anterior",
  "sensor.balance_hidrico_lluvia_efectiva",
  "sensor.balance_hidrico_proximo_ciclo",
  "sensor.balance_hidrico_ultimo_ciclo",
  "binary_sensor.balance_hidrico_aplazado_por_lluvia_prevista",
  "switch.balance_hidrico_modo_simulacion",
];

const porZona = (z) => [
  `sensor.zona_${z}_estado`,
  `sensor.zona_${z}_deficit_acumulado`,
  `sensor.zona_${z}_falta_para_regar`,
  `sensor.zona_${z}_volumen_objetivo`,
  `sensor.zona_${z}_kc_del_mes`,
  `sensor.zona_${z}_caudal_aprendido`,
  `sensor.zona_${z}_litros_del_ultimo_ciclo`,
  `sensor.zona_${z}_litros_de_la_temporada`,
  `sensor.zona_${z}_ultimo_riego`,
  `binary_sensor.zona_${z}_bloqueada`,
  `binary_sensor.zona_${z}_regando`,
  `switch.zona_${z}_habilitada`,
  `number.zona_${z}_superficie`,
  `number.zona_${z}_umbral_de_riego`,
  `number.zona_${z}_techo_de_seguridad`,
  `number.zona_${z}_coeficiente_de_ajuste`,
];

const ZONAS = { frutales: "Frutales", aptenia: "Aptenia", cipreses: "Cipreses" };
const TECHOS = { frutales: 800, aptenia: 450, cipreses: 350 };

const hass = { entities: {}, devices: {}, states: {} };

const registrar = (entityId, deviceId, nombreDispositivo) => {
  hass.entities[entityId] = { entity_id: entityId, platform: "riego", device_id: deviceId };
  const corto = entityId.split(".")[1].split("_").slice(-2).join(" ");
  hass.states[entityId] = {
    state: "1",
    attributes: { friendly_name: `${nombreDispositivo} ${corto}` },
  };
};

hass.devices["dev_sistema"] = { name: "Balance Hídrico" };
for (const e of SISTEMA) registrar(e, "dev_sistema", "Balance Hídrico");

for (const [zid, nombre] of Object.entries(ZONAS)) {
  const dev = `dev_${zid}`;
  hass.devices[dev] = { name: `Zona ${nombre}` };
  for (const e of porZona(zid)) registrar(e, dev, `Zona ${nombre}`);
  hass.states[`number.zona_${zid}_techo_de_seguridad`].state = String(TECHOS[zid]);
}

// Una entidad deshabilitada no debe aparecer en ninguna tarjeta.
hass.entities["sensor.zona_frutales_oculta"] = {
  entity_id: "sensor.zona_frutales_oculta",
  platform: "riego",
  device_id: "dev_frutales",
  disabled_by: "user",
};
// Ni una entidad de otra integración.
hass.entities["sensor.riego_frutales_battery"] = {
  entity_id: "sensor.riego_frutales_battery",
  platform: "mqtt",
  device_id: "dev_z2m",
};

// ── Generación ──────────────────────────────────────────────────────────
const panel = await Estrategia.generate({}, hass);
const vistas = panel.views;

assert.equal(vistas.length, 2, "se esperan dos vistas");
const [resumen, detalle] = vistas;
assert.equal(resumen.path, "resumen");
assert.equal(detalle.path, "detalle");

/** Recorre todas las tarjetas de una vista. */
function* tarjetas(vista) {
  for (const seccion of vista.sections || []) {
    for (const c of seccion.cards || []) yield c;
  }
}

/** Todos los entity_id que una tarjeta referencia. */
function referencias(card) {
  const salida = [];
  if (card.entity) salida.push(card.entity);
  for (const e of card.entities || []) salida.push(typeof e === "string" ? e : e.entity);
  return salida.filter(Boolean);
}

const todas = [...tarjetas(resumen), ...tarjetas(detalle)];
assert.ok(todas.length > 40, `pocas tarjetas: ${todas.length}`);

// 1. Ninguna tarjeta apunta a una entidad inexistente, deshabilitada o ajena.
for (const card of todas) {
  for (const ref of referencias(card)) {
    assert.ok(hass.states[ref], `tarjeta ${card.type} referencia ${ref}, que no existe`);
    assert.ok(
      !hass.entities[ref]?.disabled_by,
      `tarjeta ${card.type} referencia ${ref}, deshabilitada`
    );
    assert.equal(
      hass.entities[ref].platform,
      "riego",
      `tarjeta ${card.type} referencia ${ref}, que no es de la integración`
    );
  }
}

// 2. numeric-input solo admite "buttons" y "slider".
for (const card of todas) {
  for (const f of card.features || []) {
    if (f.type === "numeric-input") {
      assert.ok(
        ["buttons", "slider"].includes(f.style),
        `style inválido en numeric-input: ${JSON.stringify(f.style)}`
      );
    }
    assert.notEqual(f.type, "switch-toggle", "switch-toggle no existe; es toggle");
  }
}

// 3. Superficie y techo se teclean; umbral y coeficiente van a botones.
const tiposPorEntidad = new Map();
for (const card of todas) {
  for (const ref of referencias(card)) {
    if (!tiposPorEntidad.has(ref)) tiposPorEntidad.set(ref, []);
    tiposPorEntidad.get(ref).push(card.type);
  }
}
for (const zid of Object.keys(ZONAS)) {
  for (const sufijo of ["umbral_de_riego", "coeficiente_de_ajuste"]) {
    assert.ok(
      tiposPorEntidad.get(`number.zona_${zid}_${sufijo}`)?.includes("tile"),
      `${sufijo} de ${zid} debería ser un tile con botones`
    );
  }
  for (const sufijo of ["superficie", "techo_de_seguridad"]) {
    assert.ok(
      tiposPorEntidad.get(`number.zona_${zid}_${sufijo}`)?.includes("entities"),
      `${sufijo} de ${zid} debería ir en una tarjeta entities`
    );
  }
}

// 4. «Previsto» es una proyección EN VIVO (§7.18): usa el ET₀ acumulado del
// sistema y el déficit/Kc/factor de cada zona, no el volumen_objetivo
// congelado de la integración, que solo se recalcula una vez al día.
const previsto = [...tarjetas(resumen)].find(
  (c) => c.type === "markdown" && c.content.includes("En vivo")
);
assert.ok(previsto, "falta la tarjeta «Previsto para el próximo ciclo»");
assert.ok(!previsto.content.includes("''"), "hay un states('') en el previsto");
assert.ok(
  previsto.content.includes("sensor.balance_hidrico_et0_acumulada_del_periodo"),
  "el previsto no usa el ET₀ acumulado en vivo"
);
assert.ok(
  previsto.content.includes("sensor.balance_hidrico_lluvia_efectiva"),
  "el previsto no descuenta la lluvia efectiva"
);
for (const zid of Object.keys(ZONAS)) {
  for (const sufijo of ["deficit_acumulado", "umbral_de_riego", "superficie", "techo_de_seguridad"]) {
    const prefijo = sufijo === "umbral_de_riego" || sufijo === "superficie" || sufijo === "techo_de_seguridad"
      ? "number"
      : "sensor";
    assert.ok(
      previsto.content.includes(`${prefijo}.zona_${zid}_${sufijo}`),
      `el previsto no usa ${sufijo} de ${zid}`
    );
  }
}
assert.ok(
  previsto.content.includes("kc_mes") && previsto.content.includes("factor_zona"),
  "el previsto debe leer kc_mes y factor_zona del sensor de déficit, no reinventar el cálculo"
);
// No debe quedar ningún medidor: mostraba volumen_objetivo, que se congela
// nada más regar y se queda casi siempre en 0 con umbrales bajos.
assert.equal(
  [...tarjetas(resumen)].filter((c) => c.type === "gauge").length,
  0,
  "no deberían quedar tarjetas gauge en el Resumen"
);

// 5. La plantilla del markdown no deja marcadores sin sustituir y no
//    llama a states('') por una entidad que no se encontró.
const markdown = [...tarjetas(resumen)].find((c) => c.type === "markdown");
assert.ok(markdown, "falta la tarjeta de resumen");
for (const marcador of [
  "SENSOR_PROXIMO",
  "SWITCH_SIM",
  "BINARY_APLAZADO",
  "SENSOR_ET0_ANTERIOR",
  "SENSOR_ET0_ACUM",
  "SENSOR_LLUVIA",
]) {
  assert.ok(!markdown.content.includes(marcador), `marcador sin sustituir: ${marcador}`);
}
assert.ok(!markdown.content.includes("''"), "hay un states('') por una entidad no encontrada");
for (const nombre of Object.values(ZONAS)) {
  assert.ok(markdown.content.includes(`'${nombre}'`), `${nombre} falta en la tabla`);
}

// 5b. La segunda tarjeta de texto resume el último riego.
const [cabecera, ultimo] = [...tarjetas(resumen)].filter((c) => c.type === "markdown");
assert.equal(
  [...tarjetas(resumen)].filter((c) => c.type === "markdown").length,
  3,
  "se esperan tres tarjetas de texto: cabecera, último riego y previsto"
);
assert.ok(ultimo, "falta la tarjeta de último riego");
assert.ok(!ultimo.content.includes("''"), "hay un states('') en el último riego");
for (const zid of Object.keys(ZONAS)) {
  for (const sufijo of ["litros_del_ultimo_ciclo", "ultimo_riego"]) {
    assert.ok(
      ultimo.content.includes(`sensor.zona_${zid}_${sufijo}`),
      `el último riego no usa ${sufijo} de ${zid}`
    );
  }
}
assert.ok(
  ultimo.content.includes("sensor.balance_hidrico_ultimo_ciclo"),
  "el último riego debe anclarse al ciclo, o mostraría riegos de días previos"
);

// 5c. Con el déficit a cero la cabecera no debe anunciar "0 L previstos".
assert.ok(
  cabecera.content.includes("Sin riego pendiente"),
  "falta la rama de la cabecera para cuando no hay nada que regar"
);

// 5d. La cabecera usa la MISMA proyección en vivo que "Previsto" (§7.18):
// nunca debe decidir su titular ni su tabla con volumen_objetivo, que se
// congela nada más regar. Si esto falla, el panel puede volver a
// contradecirse: arriba "sin riego pendiente", abajo litros previstos.
assert.ok(
  !cabecera.content.includes("volumen_objetivo"),
  "la cabecera no debe usar el volumen_objetivo congelado"
);
assert.ok(
  cabecera.content.includes("sensor.balance_hidrico_et0_acumulada_del_periodo") &&
    cabecera.content.includes("sensor.balance_hidrico_lluvia_efectiva"),
  "la cabecera debe proyectar con el ET₀ acumulado y la lluvia efectiva en vivo"
);
for (const zid of Object.keys(ZONAS)) {
  for (const sufijo of ["deficit_acumulado", "superficie", "techo_de_seguridad"]) {
    const prefijo = sufijo === "deficit_acumulado" ? "sensor" : "number";
    assert.ok(
      cabecera.content.includes(`${prefijo}.zona_${zid}_${sufijo}`),
      `la cabecera no usa ${sufijo} de ${zid} para proyectar`
    );
  }
}
// Cada marcador SENSOR_ET0_ACUM / SENSOR_LLUVIA se usa dos veces en la
// plantilla (proyección + línea informativa): un .replace() sin "All"
// solo sustituye la primera y deja la segunda literal.
assert.ok(
  !cabecera.content.includes("SENSOR_"),
  "quedó un marcador SENSOR_* sin sustituir en la cabecera"
);

// 6. El orden de los sensores de zona es el previsto, no el alfabético.
const seccionFrutales = detalle.sections.find((s) =>
  s.cards.some((c) => c.heading === "Zona Frutales")
);
const sensoresFrutales = seccionFrutales.cards
  .filter((c) => c.type === "tile" && c.entity.startsWith("sensor."))
  .map((c) => c.entity);
assert.equal(
  sensoresFrutales[0],
  "sensor.zona_frutales_estado",
  `el primer sensor debería ser el estado, no ${sensoresFrutales[0]}`
);
assert.equal(sensoresFrutales[1], "sensor.zona_frutales_deficit_acumulado");
assert.ok(
  sensoresFrutales.length === 9,
  `faltan sensores en la zona: ${sensoresFrutales.length}`
);

// 7. Las anchuras respetan la rejilla de 12 × column_span.
for (const seccion of resumen.sections) {
  const total = 12 * (seccion.column_span || 1);
  for (const card of seccion.cards) {
    const cols = card.grid_options?.columns;
    if (typeof cols === "number") {
      assert.ok(cols <= total, `${card.type} pide ${cols} columnas de ${total}`);
    }
  }
}

// 8. Sin entidades, un aviso en vez de un panel roto.
const vacio = await Estrategia.generate({}, { entities: {}, devices: {}, states: {} });
assert.equal(vacio.views.length, 1);
assert.equal(vacio.views[0].cards[0].type, "markdown");

console.log(`Todo correcto · ${todas.length} tarjetas, ${vistas.length} vistas`);
