"""Pruebas de la integración Riego. Se ejecutan sin pytest:

    python3 tests/test_riego.py

Las de ET₀ no necesitan Home Assistant. Las del flujo de configuración y del
coordinador sí; si no está instalado, se saltan indicándolo.
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

CEST = timezone(timedelta(hours=2))
LAT, LON, ALT = 38.4115, -0.55025, 120.0

fallos: list[str] = []


def comprobar(condicion: bool, etiqueta: str) -> None:
    if condicion:
        print(f"  OK    {etiqueta}")
    else:
        print(f"  FALLO {etiqueta}")
        fallos.append(etiqueta)


def casi(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(a - b) <= tol


# ── ET₀ ───────────────────────────────────────────────────────────────


def test_et0() -> None:
    from custom_components.riego import et0

    print("\nET₀ — Penman-Monteith FAO-56 horaria")

    # La constante psicrométrica debe calcularse con la presión en kPa.
    # Este es el error que tenía la plantilla YAML original y que hacía que
    # la ET₀ saliera un ~40 % por debajo de lo real.
    r = et0.calcular(
        temperatura_c=27.0, humedad_pct=50.0, radiacion_wm2=325.15,
        viento_ms=1.072 / 3.6, presion_hpa=1003.3,
        momento=datetime(2026, 9, 13, 18, 2, 50, tzinfo=CEST),
        latitud=LAT, longitud=LON, altitud_m=ALT, offset_utc_horas=2.0,
    )
    comprobar(0.20 <= r.et0 <= 0.22, f"tarde despejada de septiembre = {r.et0:.4f} mm/h (esperado ~0.209)")

    # De noche la ET₀ nunca es negativa, aunque Rn sí lo sea.
    noche = et0.calcular(
        temperatura_c=18.0, humedad_pct=80.0, radiacion_wm2=0.0,
        viento_ms=0.5, presion_hpa=1010.0,
        momento=datetime(2026, 9, 13, 3, 0, tzinfo=CEST),
        latitud=LAT, longitud=LON, altitud_m=ALT, offset_utc_horas=2.0,
    )
    comprobar(noche.et0 >= 0, f"ET₀ nocturna no negativa = {noche.et0:.4f}")
    comprobar(noche.rn < 0, f"Rn nocturna sí negativa = {noche.rn:.4f}")
    comprobar(casi(noche.ra, 0.0), "Ra nocturna = 0")

    # Corrección de viento a 2 m, FAO-56 Ec.47
    comprobar(casi(et0.correccion_viento(2.0), 1.0), "corrección de viento a 2 m = 1.0")
    comprobar(abs(et0.correccion_viento(7.0) - 0.7921) < 1e-3, "corrección 7 m → 2 m ≈ 0.7921")

    # Rso de cielo despejado a mediodía solar en septiembre: ~814 W/m².
    # La tabla del YAML antiguo decía 411, la mitad.
    mediodia = et0.radiacion_extraterrestre_horaria(
        datetime(2026, 9, 13, 14, 0, tzinfo=CEST), LAT, LON, 2.0
    )
    rso_wm2 = (0.75 + 2e-5 * ALT) * mediodia / 0.0036
    comprobar(780 <= rso_wm2 <= 850, f"Rso a mediodía solar = {rso_wm2:.0f} W/m² (la tabla vieja: 411)")

    # Un día real integrado debe caer en la climatología de Alicante.
    Rs = [0, 0, 0, 0, 0, 0, 0, 4.10, 77.11, 256.98, 419.40, 631.65, 729.76,
          875.16, 876.62, 801.06, 659.30, 453.26, 227.95, 50.79, 3.26, 0, 0, 0]
    T = [21.58, 21.48, 21.31, 21.28, 21.14, 21.04, 21.04, 20.70, 21.89, 24.73,
         25.44, 26.36, 26.88, 26.62, 26.85, 26.92, 26.55, 26.13, 25.79, 25.09,
         24.19, 23.26, 22.75, 22.21]
    RH = [77.31, 77.41, 78.38, 77.20, 76.69, 77.46, 78.00, 78.95, 74.77, 64.14,
          57.97, 54.13, 51.95, 51.26, 49.40, 48.60, 52.23, 54.85, 59.91, 64.47,
          69.50, 73.81, 75.44, 76.28]
    W = [1.05, 2.38, 1.98, 2.22, 2.17, 1.64, 2.24, 1.99, 1.79, 3.73, 5.26, 4.25,
         8.04, 11.76, 12.54, 12.93, 10.32, 10.90, 10.99, 9.19, 4.56, 0.46, 0.22, 0.97]
    base = datetime(2026, 9, 12, 0, 30, tzinfo=timezone.utc)
    total = sum(
        et0.calcular(
            temperatura_c=T[i], humedad_pct=RH[i], radiacion_wm2=Rs[i],
            viento_ms=W[i] / 3.6, presion_hpa=1010.0,
            momento=(base + timedelta(hours=i)).astimezone(CEST),
            latitud=LAT, longitud=LON, altitud_m=ALT, offset_utc_horas=2.0,
        ).et0
        for i in range(24)
    )
    comprobar(3.9 <= total <= 5.0, f"día real 12/09 integrado = {total:.2f} mm/día (climatología 3.9-4.5)")

    # Presión estimada desde la altitud, FAO-56 Ec.7
    comprobar(abs(et0.presion_desde_altitud(120.0) - 999.0) < 1.5,
              f"presión estimada a 120 m = {et0.presion_desde_altitud(120.0):.1f} hPa")
    comprobar(abs(et0.presion_desde_altitud(0.0) - 1013.0) < 0.5, "a nivel del mar = 1013 hPa")

    # Elegir la presión relativa en vez de la absoluta mueve la ET₀ muy poco
    # a esta altitud. Respalda lo que se le dijo al usuario.
    comun = dict(
        temperatura_c=27.0, humedad_pct=50.0, radiacion_wm2=325.15,
        viento_ms=1.072 / 3.6,
        momento=datetime(2026, 9, 13, 18, 2, 50, tzinfo=CEST),
        latitud=LAT, longitud=LON, altitud_m=ALT, offset_utc_horas=2.0,
    )
    abs_ = et0.calcular(presion_hpa=1003.4, **comun).et0
    rel_ = et0.calcular(presion_hpa=1017.7, **comun).et0
    desvio = abs(rel_ - abs_) / abs_ * 100
    comprobar(desvio < 0.5, f"absoluta vs relativa a 120 m: {desvio:.2f} % de diferencia (<0.5 %)")


def test_irradiancia_desde_lux() -> None:
    """Un sensor de lux debe poder sustituir al de radiación."""
    from custom_components.riego import et0
    from custom_components.riego.const import DEFECTO_FACTOR_LUX

    print("\nIrradiancia a partir de iluminancia")

    comun = dict(
        temperatura_c=27.0, humedad_pct=50.0, viento_ms=0.3, presion_hpa=1003.4,
        momento=datetime(2026, 9, 13, 18, 2, 50, tzinfo=CEST),
        latitud=LAT, longitud=LON, altitud_m=ALT, offset_utc_horas=2.0,
    )
    directa = et0.calcular(radiacion_wm2=325.15, **comun).et0
    # 325.15 W/m² son los 41197 lx que publica la propia estación
    desde_lux = et0.calcular(radiacion_wm2=41196.5 / DEFECTO_FACTOR_LUX, **comun).et0
    comprobar(casi(directa, desde_lux, 1e-4),
              f"lux ÷ 126.7 reproduce la radiación ({directa:.4f} vs {desde_lux:.4f} mm/h)")


# ── Flujo de configuración ────────────────────────────────────────────


def test_config_flow() -> None:
    import homeassistant  # noqa: F401  debe importarse antes que probatio/voluptuous
    from probatio import to_field_list
    from unittest.mock import MagicMock

    from homeassistant.helpers import config_validation as cv

    from custom_components.riego.config_flow import RiegoConfigFlow, RiegoOptionsFlow

    print("\nFlujo de configuración")

    def serializable(resultado: dict, etiqueta: str) -> None:
        if not resultado.get("data_schema"):
            comprobar(True, f"{etiqueta} (sin esquema)")
            return
        campos = to_field_list(resultado["data_schema"], custom_serializer=cv.custom_serializer)
        json.dumps(campos)  # es lo que HA envía al frontend
        comprobar(len(campos) > 0, f"{etiqueta}: {len(campos)} campos serializan a JSON")

    # El formulario debe tener EXACTAMENTE estos campos, y los numéricos sus
    # límites correctos. Un descuido editando el esquema dejó una vez el campo
    # "luxes por W/m²" con los límites del factor del piranómetro (0.5-1.5),
    # de modo que el valor por defecto 126.7 se rechazaba por «too large».
    from custom_components.riego.config_flow import esquema_meteo
    from custom_components.riego.const import DEFECTO_FACTOR_LUX, DEFECTO_FACTOR_RADIACION

    campos = {c["name"]: c for c in to_field_list(esquema_meteo({}),
                                                  custom_serializer=cv.custom_serializer)}
    esperados = {"sensor_temperatura", "sensor_humedad", "sensor_radiacion",
                 "sensor_iluminancia", "factor_lux", "sensor_viento", "sensor_presion",
                 "sensor_lluvia_24h", "altura_anemometro", "viento_minimo",
                 "factor_radiacion"}
    comprobar(set(campos) == esperados,
              f"el paso de meteorología tiene los 11 campos esperados (faltan: "
              f"{esperados - set(campos)}, sobran: {set(campos) - esperados})")

    for nombre, defecto in (("factor_lux", DEFECTO_FACTOR_LUX),
                            ("factor_radiacion", DEFECTO_FACTOR_RADIACION),
                            ("altura_anemometro", 7.0), ("viento_minimo", 0.0)):
        num = campos.get(nombre, {}).get("selector", {}).get("number", {})
        dentro = num and num["min"] <= defecto <= num["max"]
        comprobar(bool(dentro),
                  f"{nombre}: el valor por defecto {defecto} cabe en "
                  f"[{num.get('min')}, {num.get('max')}]")

    # Ningún esquema puede tener un booleano OBLIGATORIO: ha-form considera
    # que un booleano required con valor false está «sin rellenar» y bloquea
    # el botón de envío sin mostrar error. Fue lo que impidió terminar el
    # alta en v0.2.1: la casilla «añadir otra zona», al desmarcarla, dejaba
    # el formulario muerto.
    from custom_components.riego import config_flow as cf_mod

    obligatorios = []
    for nombre, constructor in (("meteo", cf_mod.esquema_meteo),
                                ("prevision", cf_mod.esquema_prevision),
                                ("ciclo", cf_mod.esquema_ciclo),
                                ("zona", cf_mod.esquema_zona)):
        for campo in to_field_list(constructor({}), custom_serializer=cv.custom_serializer):
            es_bool = campo.get("type") == "boolean" or "boolean" in campo.get("selector", {})
            if es_bool and campo.get("required"):
                obligatorios.append(f"{nombre}.{campo['name']}")
    comprobar(not obligatorios,
              f"ningún esquema tiene booleanos obligatorios (los hay en: {obligatorios})")

    meteo = {"sensor_temperatura": "sensor.t", "sensor_humedad": "sensor.h",
             "sensor_radiacion": "sensor.r", "altura_anemometro": 7.0,
             "viento_minimo": 0.0, "factor_radiacion": 1.0, "factor_lux": 126.7}
    prev = {"forecast_tipo": "hourly", "forecast_horas": 24, "lluvia_prevista_umbral": 3.0,
            "lluvia_minima": 2.0, "lluvia_cap": 20.0, "temp_helada": 1.0}
    ciclo = {"modo_inicio": "fin_amanecer", "offset_amanecer_min": -35,
             "hora_fija_valor": "03:00:00", "hora_minima": "00:00:00",
             "margen_duracion": 15, "desfase_zonas": 60, "deficit_maximo": 50.0,
             "simulacion": True}
    zona = {"nombre": "Frutales", "m2": 140.0, "umbral": 0.5, "techo": 800.0, "factor": 1.0,
            "kc": "0.42,0.42,0.52,0.63,0.74,0.76,0.76,0.76,0.71,0.63,0.50,0.42",
            "topic": "zigbee2mqtt/Riego Frutales/set", "caudal_defecto": 289.0}

    async def recorrido() -> None:
        f = RiegoConfigFlow()
        f.hass = MagicMock()
        f._async_current_entries = lambda **k: []
        serializable(await f.async_step_user(None), "paso user")

        sin_luz = await f.async_step_user({k: v for k, v in meteo.items()
                                           if k != "sensor_radiacion"})
        comprobar(sin_luz.get("errors", {}).get("base") == "falta_irradiancia",
                  "sin radiación ni lux se rechaza")
        solo_lux = dict(meteo); solo_lux.pop("sensor_radiacion")
        solo_lux["sensor_iluminancia"] = "sensor.lux"
        serializable(await f.async_step_user(solo_lux), "solo con sensor de lux")

        serializable(await f.async_step_user(meteo), "paso previsión")
        serializable(await f.async_step_prevision(prev), "paso ciclo")
        serializable(await f.async_step_ciclo(ciclo), "paso zona")
        serializable(await f.async_step_zona(zona), "paso otra")

        malo = await f.async_step_zona(dict(zona, kc="0.4, 0.4"))
        comprobar(malo.get("errors", {}).get("kc") == "kc_invalido", "Kc con 2 valores se rechaza")
        sin_topic = await f.async_step_zona(dict(zona, topic=""))
        comprobar(sin_topic.get("errors", {}).get("topic") == "topic_requerido", "zona sin topic se rechaza")

        # El paso final es un menú, no una casilla: un formulario con una sola
        # casilla desmarcada parecía una pantalla sin acción y la entrada no
        # llegaba a crearse si no se pulsaba «Enviar».
        menu = await f.async_step_otra(None)
        tipo = menu["type"].value if hasattr(menu["type"], "value") else menu["type"]
        comprobar(tipo == "menu", f"el paso final es un menú (es {tipo})")
        comprobar(menu.get("menu_options") == ["zona", "finalizar"],
                  f"el menú ofrece añadir zona o terminar: {menu.get('menu_options')}")

        # Se usa el async_create_entry REAL de Home Assistant, no un doble: el
        # doble ocultaba que este camino no se estaba ejercitando de verdad.
        f.flow_id, f.handler, f.context = "test", "riego", {"source": "user"}
        final = await f.async_step_finalizar(None)
        tipo = final["type"].value if hasattr(final["type"], "value") else final["type"]
        comprobar(tipo == "create_entry", f"terminar crea la entrada (devuelve {tipo})")
        comprobar(final.get("title") == "Riego", "la entrada se titula Riego")
        zonas = final["data"]["zonas"]
        comprobar(zonas[0]["id"] == "frutales", "id de zona derivado del nombre")
        comprobar(zonas[0]["kc"] == [0.42, 0.42, 0.52, 0.63, 0.74, 0.76, 0.76, 0.76,
                                     0.71, 0.63, 0.5, 0.42], "los 12 Kc se parsean a float")

        o = RiegoOptionsFlow()
        o.hass = MagicMock()
        entrada = MagicMock()
        entrada.data = {**meteo, **prev, **ciclo, "zonas": zonas}
        entrada.options = {}
        type(o).config_entry = property(lambda self: entrada)
        serializable(await o.async_step_meteo(None), "opciones meteo")
        serializable(await o.async_step_prevision(None), "opciones previsión")
        serializable(await o.async_step_ciclo(None), "opciones ciclo")
        serializable(await o.async_step_zonas(None), "opciones zonas")
        o._zona_editada = "frutales"
        serializable(await o.async_step_editar_zona(None), "opciones editar zona")

    asyncio.run(recorrido())


def test_traducciones() -> None:
    """Los JSON deben ser válidos y cubrir todos los pasos y errores."""
    import json

    print("\nFicheros de traducción")
    base = RAIZ / "custom_components" / "riego"
    ficheros = ["strings.json", "translations/es.json", "translations/en.json"]
    cargados = {}
    for nombre in ficheros:
        ruta = base / nombre
        try:
            cargados[nombre] = json.loads(ruta.read_text())
            comprobar(True, f"{nombre} es JSON válido")
        except Exception as err:  # noqa: BLE001
            comprobar(False, f"{nombre} es JSON válido ({err})")
            return

    from custom_components.riego import config_flow as cf

    # Solo los pasos propios: dir() arrastra los de descubrimiento que hereda
    # de ConfigFlow (dhcp, ssdp, zeroconf...), que no llevan texto. Y
    # "finalizar" no pinta pantalla, crea la entrada y punto.
    sin_pantalla = {"finalizar"}
    pasos_config = {n[len("async_step_"):] for n in vars(cf.RiegoConfigFlow)
                    if n.startswith("async_step_")} - sin_pantalla
    pasos_opciones = {n[len("async_step_"):] for n in vars(cf.RiegoOptionsFlow)
                      if n.startswith("async_step_")} - sin_pantalla
    for nombre, d in cargados.items():
        faltan = pasos_config - set(d.get("config", {}).get("step", {}))
        comprobar(not faltan, f"{nombre}: todos los pasos del alta tienen texto (faltan {faltan})")
        faltan = pasos_opciones - set(d.get("options", {}).get("step", {}))
        comprobar(not faltan, f"{nombre}: todos los pasos de opciones tienen texto (faltan {faltan})")

    for nombre, d in cargados.items():
        otra = d["config"]["step"]["otra"]
        comprobar(set(otra.get("menu_options", {})) == {"zona", "finalizar"},
                  f"{nombre}: el paso final ofrece las dos opciones del menú")


# ── Coordinador ───────────────────────────────────────────────────────


def test_coordinador() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from homeassistant.core import State

    from custom_components.riego import coordinator as mod
    from custom_components.riego.coordinator import RiegoCoordinator

    print("\nCoordinador — ciclo de riego")

    ZONAS = [
        {"id": "frutales", "nombre": "Frutales", "m2": 140.0, "umbral": 0.5, "techo": 800.0,
         "factor": 1.0, "kc": [0.42, 0.42, 0.52, 0.63, 0.74, 0.76, 0.76, 0.76, 0.71, 0.63, 0.50, 0.42],
         "topic": "z2m/Frutales/set", "sensor_estado": "sensor.f_estado",
         "sensor_caudal": "sensor.f_caudal", "caudal_defecto": 289.0},
        {"id": "aptenia", "nombre": "Aptenia", "m2": 80.0, "umbral": 0.5, "techo": 450.0,
         "factor": 1.0, "kc": [0.32, 0.32, 0.40, 0.52, 0.62, 0.68, 0.68, 0.65, 0.55, 0.44, 0.36, 0.32],
         "topic": "z2m/Aptenia/set", "sensor_estado": "sensor.a_estado", "caudal_defecto": 286.0},
    ]

    class Estados:
        def __init__(self) -> None:
            self._d: dict[str, State] = {}

        def set(self, eid: str, valor, attrs=None) -> None:
            self._d[eid] = State(eid, str(valor), attrs or {})

        def get(self, eid: str):
            return self._d.get(eid)

    def construir(simulacion: bool = False, **extra):
        hass = MagicMock()
        hass.states = Estados()
        hass.config.latitude, hass.config.longitude, hass.config.elevation = LAT, LON, ALT
        hass.services.async_call = AsyncMock(return_value={})
        hass.bus.async_fire = MagicMock()

        entrada = MagicMock()
        entrada.entry_id = "test"
        entrada.data = {
            "sensor_temperatura": "sensor.temp", "sensor_humedad": "sensor.hum",
            "sensor_radiacion": "sensor.rad", "sensor_lluvia_24h": "sensor.lluvia",
            "zonas": ZONAS, "desfase_zonas": 0, "simulacion": simulacion,
            "lluvia_minima": 2.0, "lluvia_cap": 20.0, "temp_helada": 1.0,
            "deficit_maximo": 50.0, "modo_inicio": "fin_amanecer",
            "margen_duracion": 15, "hora_minima": "00:00:00", **extra,
        }
        entrada.options = {}

        with patch.object(mod, "async_track_time_interval"), \
             patch.object(mod, "async_track_state_change_event"), \
             patch.object(mod, "async_track_point_in_utc_time"), \
             patch.object(mod, "get_astral_event_next",
                          return_value=datetime(2026, 9, 14, 5, 50, tzinfo=timezone.utc)):
            c = RiegoCoordinator(hass, entrada)
        c._store = MagicMock()
        c._store.async_load = AsyncMock(return_value={})
        c._store.async_save = AsyncMock()
        c.async_refresh = AsyncMock()
        c._estado = {"et0_acumulada": 0.0, "et0_periodo_anterior": 0.0, "et0_previa": 0.0,
                     "ultima_integracion": None, "aplazado_lluvia": False,
                     "ultimo_ciclo": None, "zonas": {}, "simulacion": simulacion}
        for z in ZONAS:
            c.runtime(z["id"]).update({"deficit": 0.0, "litros_hoy": 0.0, "litros_temporada": 0.0})

        hass.states.set("sensor.temp", 22.0)
        hass.states.set("sensor.hum", 55)
        hass.states.set("sensor.rad", 0.0)
        hass.states.set("sensor.lluvia", 0.0)
        hass.states.set("sensor.f_estado", "normal_state")
        hass.states.set("sensor.a_estado", "normal_state")
        hass.states.set("sensor.f_caudal", 0.0)
        return c, hass

    publicados: list[tuple[str, dict]] = []

    async def fake_publish(hass, topic, payload, **kw):
        publicados.append((topic, json.loads(payload)))

    # 1. Ciclo normal: ET₀ acumulada de 3.1 mm en septiembre
    c, hass = construir()
    c._estado["et0_acumulada"] = 3.10
    publicados.clear()
    with patch.object(mod.mqtt, "async_publish", side_effect=fake_publish), \
         patch.object(mod, "get_astral_event_next",
                      return_value=datetime(2026, 9, 14, 5, 50, tzinfo=timezone.utc)):
        resumen = asyncio.run(c.ejecutar_ciclo())

    frutales = next(p for t, p in publicados if "Frutales" in t)
    litros_f = frutales["cyclic_quantitative_irrigation"]["irrigation_capacity"]
    comprobar(litros_f == 308, f"Frutales: 3.10 × 0.71 × 140 m² = {litros_f} L (esperado 308)")
    comprobar(casi(c.deficit("frutales"), 0.0, 0.01), "déficit de Frutales queda a 0 tras regar")
    aptenia = next(p for t, p in publicados if "Aptenia" in t)
    # 3.10 × 0.55 = 1.705 → el déficit se redondea a 1.71 mm antes de pasar a
    # litros, así que salen 137 y no 136. Es exactamente lo que la instalación
    # real envió a esta zona el 13/09/2026.
    comprobar(aptenia["cyclic_quantitative_irrigation"]["irrigation_capacity"] == 137,
              "Aptenia: 3.10 × 0.55 × 80 m² = 137 L (igual que la instalación real)")
    comprobar(casi(c._estado["et0_acumulada"], 0.0), "el acumulado de ET₀ se pone a cero")
    comprobar(c._estado["et0_periodo_anterior"] == 3.10, "se guarda la ET₀ del periodo")

    # 2. El techo recorta y el resto del déficit queda pendiente
    c, hass = construir()
    c._estado["et0_acumulada"] = 9.0          # 9 × 0.71 × 140 = 894 L, techo 800
    publicados.clear()
    with patch.object(mod.mqtt, "async_publish", side_effect=fake_publish):
        asyncio.run(c.ejecutar_ciclo())
    litros = next(p for t, p in publicados if "Frutales" in t)["cyclic_quantitative_irrigation"]["irrigation_capacity"]
    comprobar(litros == 800, f"el techo recorta a {litros} L")
    comprobar(c.deficit("frutales") > 0.6,
              f"queda déficit pendiente tras el recorte: {c.deficit('frutales')} mm")

    # 3. Helada: no se riega y el déficit se conserva
    c, hass = construir()
    c._estado["et0_acumulada"] = 3.10
    hass.states.set("sensor.temp", -2.0)
    publicados.clear()
    with patch.object(mod.mqtt, "async_publish", side_effect=fake_publish):
        resumen = asyncio.run(c.ejecutar_ciclo())
    comprobar(resumen["resultado"] == "helada", "con −2 °C el ciclo se detiene por helada")
    comprobar(not publicados, "no se publica nada con helada")
    comprobar(c.deficit("frutales") > 2.0, "el déficit se conserva tras la helada")

    # 4. Válvula en fallo: esa zona no riega, la otra sí
    c, hass = construir()
    c._estado["et0_acumulada"] = 3.10
    hass.states.set("sensor.f_estado", "water_leakage")
    publicados.clear()
    with patch.object(mod.mqtt, "async_publish", side_effect=fake_publish):
        resumen = asyncio.run(c.ejecutar_ciclo())
    comprobar(resumen["zonas"]["frutales"]["resultado"] == "bloqueada", "Frutales se marca bloqueada")
    comprobar(not any("Frutales" in t for t, _ in publicados), "no se riega la zona bloqueada")
    comprobar(any("Aptenia" in t for t, _ in publicados), "la otra zona sí riega")
    comprobar(c.deficit("frutales") > 2.0, "la zona bloqueada conserva su déficit")

    # 5. Modo simulación: se calcula todo pero no se abre ninguna válvula
    c, hass = construir(simulacion=True)
    c._estado["et0_acumulada"] = 3.10
    publicados.clear()
    with patch.object(mod.mqtt, "async_publish", side_effect=fake_publish):
        resumen = asyncio.run(c.ejecutar_ciclo())
    comprobar(not publicados, "en simulación no se publica MQTT")
    comprobar(resumen["zonas"]["frutales"]["litros"] == 308, "en simulación sí se calculan los litros")
    comprobar(casi(c.deficit("frutales"), 0.0, 0.01), "en simulación el déficit también se descuenta")

    # 5b. La irradiancia puede venir de un sensor de lux
    c, hass = construir()
    hass.states.set("sensor.rad", 325.15)
    con_radiacion = c._et0_instantanea().et0
    c, hass = construir(sensor_radiacion=None, sensor_iluminancia="sensor.lux",
                        factor_lux=126.7)
    hass.states.set("sensor.lux", 325.15 * 126.7)
    con_lux = c._et0_instantanea().et0
    comprobar(casi(con_radiacion, con_lux, 1e-6),
              f"el coordinador acepta lux igual que W/m² ({con_lux:.4f} mm/h)")

    # 5c. Sin sensor de presión se estima desde la altitud
    c, hass = construir(sensor_presion="sensor.presion")
    hass.states.set("sensor.presion", 1003.4)
    hass.states.set("sensor.rad", 325.15)
    con_sensor = c._et0_instantanea().et0
    c, hass = construir()  # sin sensor_presion configurado
    hass.states.set("sensor.rad", 325.15)
    sin_sensor = c._et0_instantanea().et0
    comprobar(abs(con_sensor - sin_sensor) / con_sensor < 0.01,
              "sin barómetro, la estimación por altitud queda dentro del 1 %")

    # 6. Lluvia efectiva: por debajo del mínimo no cuenta; por encima, se descuenta
    c, hass = construir()
    hass.states.set("sensor.lluvia", 1.0)
    comprobar(c._lluvia_efectiva() == 0.0, "1 mm < mínimo de 2 mm → lluvia efectiva 0")
    hass.states.set("sensor.lluvia", 50.0)
    comprobar(c._lluvia_efectiva() == 20.0, "50 mm se capan a 20 mm")

    # 7. Hora de inicio: terminar al amanecer
    c, hass = construir()
    for z in ZONAS:
        c.runtime(z["id"])["deficit"] = 2.2
    amanecer = datetime(2026, 9, 14, 5, 50, tzinfo=timezone.utc)
    inicio = c._hora_inicio(amanecer)
    minutos = (amanecer - inicio).total_seconds() / 60
    # Frutales: 2.2 × 140 = 308 L a 289 L/h = 64 min, + 15 de margen
    comprobar(75 <= minutos <= 85, f"arranque {minutos:.0f} min antes del amanecer (esperado ~79)")

    c, hass = construir()  # sin déficit no hay riego: ventana mínima
    inicio = c._hora_inicio(amanecer)
    comprobar((amanecer - inicio).total_seconds() / 60 <= 21,
              "sin nada que regar, el ciclo se pega al amanecer")

    # 8. No se programa un segundo ciclo para el mismo amanecer
    c, hass = construir()
    c._estado["ultimo_ciclo"] = datetime(2026, 9, 14, 4, 30, tzinfo=timezone.utc).isoformat()
    with patch.object(mod, "get_astral_event_next", return_value=amanecer), \
         patch.object(mod, "async_track_point_in_utc_time") as track, \
         patch.object(mod.dt_util, "utcnow",
                      return_value=datetime(2026, 9, 14, 4, 35, tzinfo=timezone.utc)):
        c._planificar()
    comprobar(c._proximo is None, "tras regar no se reprograma otro ciclo para el mismo amanecer")

    # 9. Volumen 0 si la zona está deshabilitada o no llega al umbral
    c, hass = construir()
    c.runtime("frutales")["deficit"] = 0.3
    comprobar(c.volumen_objetivo("frutales") == 0, "déficit por debajo del umbral → 0 L")
    c.runtime("frutales")["deficit"] = 2.0
    c.runtime("frutales")["habilitada"] = False
    comprobar(c.volumen_objetivo("frutales") == 0, "zona deshabilitada → 0 L")


if __name__ == "__main__":
    test_et0()
    test_irradiancia_desde_lux()
    test_traducciones()
    try:
        test_config_flow()
        test_coordinador()
    except ImportError as err:
        print(f"\n  (saltadas las pruebas que necesitan Home Assistant: {err})")

    print()
    if fallos:
        print(f"{len(fallos)} FALLOS:")
        for f in fallos:
            print("  -", f)
        sys.exit(1)
    print("Todo correcto.")
