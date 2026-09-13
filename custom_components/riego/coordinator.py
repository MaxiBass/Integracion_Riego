"""Coordinador del ciclo de riego por balance hídrico."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.components import mqtt
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import et0 as et0_mod
from .const import (
    CAUDAL_MAX_VALIDO,
    CAUDAL_MIN_VALIDO,
    CONF_ALTURA_ANEMOMETRO,
    CONF_DEFICIT_MAXIMO,
    CONF_DESFASE_ZONAS,
    CONF_FACTOR_RADIACION,
    CONF_FORECAST_HORAS,
    CONF_FORECAST_TIPO,
    CONF_HORA_FIJA,
    CONF_HORA_MINIMA,
    CONF_LLUVIA_CAP,
    CONF_LLUVIA_MINIMA,
    CONF_LLUVIA_PREVISTA,
    CONF_MARGEN_DURACION,
    CONF_MODO_INICIO,
    CONF_NOTIFY,
    CONF_OFFSET_AMANECER,
    CONF_SENSOR_HUMEDAD,
    CONF_SENSOR_LLUVIA,
    CONF_SENSOR_PRESION,
    CONF_SENSOR_RADIACION,
    CONF_SENSOR_TEMP,
    CONF_SENSOR_VIENTO,
    CONF_SIMULACION,
    CONF_TEMP_HELADA,
    CONF_VIENTO_MINIMO,
    CONF_WEATHER,
    CONF_ZONAS,
    DEFECTO_ALTURA_ANEMOMETRO,
    DEFECTO_CAUDAL,
    DEFECTO_DEFICIT_MAXIMO,
    DEFECTO_DESFASE_ZONAS,
    DEFECTO_FACTOR_RADIACION,
    DEFECTO_FACTOR_ZONA,
    DEFECTO_FORECAST_HORAS,
    DEFECTO_HORA_FIJA,
    DEFECTO_HORA_MINIMA,
    DEFECTO_KC,
    DEFECTO_LLUVIA_CAP,
    DEFECTO_LLUVIA_MINIMA,
    DEFECTO_LLUVIA_PREVISTA,
    DEFECTO_M2,
    DEFECTO_MARGEN_DURACION,
    DEFECTO_OFFSET_AMANECER,
    DEFECTO_TECHO,
    DEFECTO_TEMP_HELADA,
    DEFECTO_UMBRAL,
    DEFECTO_VIENTO_MINIMO,
    DOMAIN,
    EMA_ALFA,
    ESTADO_ACUMULANDO,
    ESTADO_BLOQUEADA,
    ESTADO_DESHABILITADA,
    ESTADO_LISTA,
    ESTADO_REGANDO,
    ESTADOS_FALLO,
    EVENTO,
    FORECAST_HORARIO,
    INTERVALO_ET0_SEGUNDOS,
    MODO_FIN_AMANECER,
    MODO_HORA_FIJA,
    MODO_OFFSET_AMANECER,
    STORAGE_KEY,
    STORAGE_VERSION,
    VOLUMEN_MIN_MUESTRA,
    Z_CAUDAL_DEFECTO,
    Z_FACTOR,
    Z_ID,
    Z_KC,
    Z_M2,
    Z_NOMBRE,
    Z_SENSOR_CAUDAL,
    Z_SENSOR_DURACION,
    Z_SENSOR_ESTADO,
    Z_SENSOR_VOLUMEN,
    Z_TECHO,
    Z_TOPIC,
    Z_UMBRAL,
)

_LOGGER = logging.getLogger(__name__)

# Cuánto antes del amanecer se planifica el ciclo del día siguiente.
VENTANA_PLANIFICACION = timedelta(hours=8)
# Margen hacia atrás desde el amanecer dentro del cual un ciclo ya ejecutado
# se considera el de ese amanecer. Menos de 24 h para no confundirlo con el
# del día anterior.
VENTANA_CICLO_CUMPLIDO = timedelta(hours=18)


def _num(estado: State | None, defecto: float = 0.0) -> float:
    """Lee un estado como float, devolviendo `defecto` si no es numérico."""
    if estado is None or estado.state in ("unknown", "unavailable", "", None):
        return defecto
    try:
        return float(estado.state)
    except (TypeError, ValueError):
        return defecto


class RiegoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Mantiene el balance hídrico, la ET₀ acumulada y ejecuta el ciclo."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._estado: dict[str, Any] = {}
        self._cancelar_ciclo = None
        self._cancelar_planificador = None
        self._desuscriptores: list[Any] = []
        self._ciclo_en_curso = False
        self._proximo: datetime | None = None

    # ── Acceso a la configuración ─────────────────────────────────────

    @property
    def opciones(self) -> dict[str, Any]:
        return {**self.entry.data, **self.entry.options}

    @property
    def zonas(self) -> list[dict[str, Any]]:
        return list(self.opciones.get(CONF_ZONAS, []))

    def zona(self, zid: str) -> dict[str, Any] | None:
        return next((z for z in self.zonas if z[Z_ID] == zid), None)

    def _opt(self, clave: str, defecto: Any) -> Any:
        valor = self.opciones.get(clave)
        return defecto if valor is None else valor

    # ── Valores en vivo (los editan las entidades number/switch) ──────
    #
    # La configuración solo siembra el valor inicial; a partir de ahí la
    # fuente de verdad es el almacén, para que ajustar un number desde el
    # panel no obligue a recargar la entrada de configuración.

    def runtime(self, zid: str) -> dict[str, Any]:
        return self._estado["zonas"].setdefault(zid, {})

    def valor_zona(self, zid: str, clave: str, defecto: Any) -> Any:
        rt = self.runtime(zid)
        if clave in rt and rt[clave] is not None:
            return rt[clave]
        cfg = self.zona(zid) or {}
        valor = cfg.get(clave)
        return defecto if valor is None else valor

    async def set_valor_zona(self, zid: str, clave: str, valor: Any) -> None:
        self.runtime(zid)[clave] = valor
        await self._guardar()
        await self.async_refresh()
        if clave in (Z_M2, Z_TECHO, Z_UMBRAL):
            self._planificar()

    @property
    def simulacion(self) -> bool:
        valor = self._estado.get(CONF_SIMULACION)
        if valor is None:
            return bool(self._opt(CONF_SIMULACION, True))
        return bool(valor)

    async def set_simulacion(self, valor: bool) -> None:
        self._estado[CONF_SIMULACION] = valor
        await self._guardar()
        await self.async_refresh()

    def habilitada(self, zid: str) -> bool:
        return bool(self.valor_zona(zid, "habilitada", True))

    # ── Arranque y parada ─────────────────────────────────────────────

    async def async_iniciar(self) -> None:
        guardado = await self._store.async_load() or {}
        self._estado = {
            "et0_acumulada": guardado.get("et0_acumulada", 0.0),
            "et0_periodo_anterior": guardado.get("et0_periodo_anterior", 0.0),
            "et0_previa": guardado.get("et0_previa", 0.0),
            "ultima_integracion": guardado.get("ultima_integracion"),
            "aplazado_lluvia": guardado.get("aplazado_lluvia", False),
            "ultimo_ciclo": guardado.get("ultimo_ciclo"),
            "zonas": guardado.get("zonas", {}),
            CONF_SIMULACION: guardado.get(CONF_SIMULACION),
        }

        for z in self.zonas:
            self.runtime(z[Z_ID]).setdefault("deficit", 0.0)
            self.runtime(z[Z_ID]).setdefault("litros_hoy", 0.0)
            self.runtime(z[Z_ID]).setdefault("litros_temporada", 0.0)

        self._desuscriptores.append(
            async_track_time_interval(
                self.hass,
                self._tick_et0,
                timedelta(seconds=INTERVALO_ET0_SEGUNDOS),
            )
        )
        self._suscribir_caudales()
        self._planificar()
        await self.async_refresh()

    async def async_parar(self) -> None:
        for cancelar in self._desuscriptores:
            cancelar()
        self._desuscriptores.clear()
        for cancelar in (self._cancelar_ciclo, self._cancelar_planificador):
            if cancelar:
                cancelar()
        self._cancelar_ciclo = None
        self._cancelar_planificador = None
        await self._guardar()

    async def _guardar(self) -> None:
        await self._store.async_save(self._estado)

    # ── ET₀: cálculo instantáneo e integración ────────────────────────

    def _et0_instantanea(self) -> et0_mod.ResultadoET0 | None:
        op = self.opciones
        obtener = self.hass.states.get

        temp = obtener(op[CONF_SENSOR_TEMP])
        hum = obtener(op[CONF_SENSOR_HUMEDAD])
        rad = obtener(op[CONF_SENSOR_RADIACION])
        if temp is None or hum is None or rad is None:
            return None
        if any(s.state in ("unknown", "unavailable") for s in (temp, hum, rad)):
            return None

        viento_ms = 0.0
        if (ent := op.get(CONF_SENSOR_VIENTO)) and (estado := obtener(ent)):
            bruto = _num(estado, 0.0)
            unidad = estado.attributes.get("unit_of_measurement", "km/h")
            viento_ms = bruto / 3.6 if unidad in ("km/h", "kph") else bruto

        presion = 1013.25
        if (ent := op.get(CONF_SENSOR_PRESION)) and (estado := obtener(ent)):
            presion = _num(estado, 1013.25)
            # Se acepta la presión tanto en hPa como en kPa
            if presion < 200:
                presion *= 10.0

        ahora = dt_util.now()
        offset = ahora.utcoffset() or timedelta(0)
        factor_rad = float(self._opt(CONF_FACTOR_RADIACION, DEFECTO_FACTOR_RADIACION))

        return et0_mod.calcular(
            temperatura_c=_num(temp, 20.0),
            humedad_pct=_num(hum, 50.0),
            radiacion_wm2=_num(rad, 0.0) * factor_rad,
            viento_ms=viento_ms,
            presion_hpa=presion,
            momento=ahora,
            latitud=self.hass.config.latitude,
            longitud=self.hass.config.longitude,
            altitud_m=float(self.hass.config.elevation or 0),
            offset_utc_horas=offset.total_seconds() / 3600.0,
            altura_anemometro_m=float(
                self._opt(CONF_ALTURA_ANEMOMETRO, DEFECTO_ALTURA_ANEMOMETRO)
            ),
            viento_minimo_ms=float(
                self._opt(CONF_VIENTO_MINIMO, DEFECTO_VIENTO_MINIMO)
            ),
        )

    async def _tick_et0(self, _ahora: datetime) -> None:
        """Integra la ET₀ instantánea al acumulado (Riemann por la izquierda)."""
        resultado = self._et0_instantanea()
        if resultado is None:
            return

        ahora = dt_util.utcnow()
        anterior = self._estado.get("ultima_integracion")
        if anterior:
            transcurrido = (ahora - dt_util.parse_datetime(anterior)).total_seconds()
            # Se descartan saltos absurdos (reinicios largos, cambios de hora)
            if 0 < transcurrido < 3600 * 3:
                incremento = self._estado["et0_previa"] * (transcurrido / 3600.0)
                self._estado["et0_acumulada"] += incremento

        self._estado["ultima_integracion"] = ahora.isoformat()
        self._estado["et0_previa"] = resultado.et0
        await self._guardar()
        await self.async_refresh()

    # ── Lluvia ────────────────────────────────────────────────────────

    def _lluvia_efectiva(self) -> float:
        ent = self.opciones.get(CONF_SENSOR_LLUVIA)
        if not ent:
            return 0.0
        bruto = _num(self.hass.states.get(ent), 0.0)
        minima = float(self._opt(CONF_LLUVIA_MINIMA, DEFECTO_LLUVIA_MINIMA))
        cap = float(self._opt(CONF_LLUVIA_CAP, DEFECTO_LLUVIA_CAP))
        return 0.0 if bruto < minima else min(bruto, cap)

    async def _lluvia_prevista(self) -> float:
        """Suma de precipitación prevista en el horizonte configurado."""
        entidad = self.opciones.get(CONF_WEATHER)
        if not entidad:
            return 0.0
        tipo = self._opt(CONF_FORECAST_TIPO, FORECAST_HORARIO)
        horas = int(self._opt(CONF_FORECAST_HORAS, DEFECTO_FORECAST_HORAS))
        try:
            respuesta = await self.hass.services.async_call(
                "weather",
                "get_forecasts",
                {"entity_id": entidad, "type": tipo},
                blocking=True,
                return_response=True,
            )
        except Exception:  # noqa: BLE001 - la previsión nunca debe tumbar el ciclo
            _LOGGER.warning("No se pudo consultar la previsión de %s", entidad, exc_info=True)
            return 0.0

        prevision = (respuesta or {}).get(entidad, {}).get("forecast", [])
        if not prevision:
            return 0.0

        tramos = horas if tipo == FORECAST_HORARIO else max(1, round(horas / 24))
        total = 0.0
        for tramo in prevision[:tramos]:
            valor = tramo.get("precipitation")
            if valor is not None:
                try:
                    total += float(valor)
                except (TypeError, ValueError):
                    continue
        return round(total, 2)

    # ── Caudal aprendido por zona ─────────────────────────────────────

    def caudal(self, zid: str) -> float:
        cfg = self.zona(zid) or {}
        defecto = float(cfg.get(Z_CAUDAL_DEFECTO) or DEFECTO_CAUDAL)
        return float(self.runtime(zid).get("caudal") or defecto)

    def _suscribir_caudales(self) -> None:
        vigilados: dict[str, str] = {}
        for z in self.zonas:
            if ent := z.get(Z_SENSOR_DURACION):
                vigilados[ent] = z[Z_ID]
        if not vigilados:
            return

        @callback
        def _al_cambiar(evento) -> None:
            zid = vigilados.get(evento.data["entity_id"])
            if zid:
                self.hass.async_create_task(self._actualizar_caudal(zid))

        self._desuscriptores.append(
            async_track_state_change_event(self.hass, list(vigilados), _al_cambiar)
        )

    async def _actualizar_caudal(self, zid: str) -> None:
        """Deriva L/h del volumen y la duración que reporta la electroválvula."""
        cfg = self.zona(zid) or {}
        ent_vol, ent_dur = cfg.get(Z_SENSOR_VOLUMEN), cfg.get(Z_SENSOR_DURACION)
        if not ent_vol or not ent_dur:
            return
        litros = _num(self.hass.states.get(ent_vol), 0.0)
        segundos = _num(self.hass.states.get(ent_dur), 0.0)
        if litros < VOLUMEN_MIN_MUESTRA or segundos <= 0:
            return
        muestra = litros / (segundos / 3600.0)
        if not CAUDAL_MIN_VALIDO <= muestra <= CAUDAL_MAX_VALIDO:
            return
        previo = self.runtime(zid).get("caudal")
        nuevo = muestra if previo is None else (1 - EMA_ALFA) * previo + EMA_ALFA * muestra
        self.runtime(zid)["caudal"] = round(nuevo, 1)
        await self._guardar()

    # ── Cálculo de volúmenes ──────────────────────────────────────────

    def kc(self, zid: str) -> float:
        cfg = self.zona(zid) or {}
        tabla = cfg.get(Z_KC) or DEFECTO_KC
        try:
            return float(tabla[dt_util.now().month - 1])
        except (IndexError, TypeError, ValueError):
            return 0.5

    def deficit(self, zid: str) -> float:
        return float(self.runtime(zid).get("deficit", 0.0))

    def volumen_objetivo(self, zid: str, deficit: float | None = None) -> int:
        """Litros a enviar a la zona, 0 si no toca regar."""
        if not self.habilitada(zid):
            return 0
        d = self.deficit(zid) if deficit is None else deficit
        umbral = float(self.valor_zona(zid, Z_UMBRAL, DEFECTO_UMBRAL))
        if d < umbral:
            return 0
        m2 = float(self.valor_zona(zid, Z_M2, DEFECTO_M2))
        techo = float(self.valor_zona(zid, Z_TECHO, DEFECTO_TECHO))
        return int(round(min(d * m2, techo)))

    def _deficit_proyectado(self, zid: str) -> float:
        """Déficit estimado en el momento del ciclo, para planificar la hora."""
        maximo = float(self._opt(CONF_DEFICIT_MAXIMO, DEFECTO_DEFICIT_MAXIMO))
        factor = float(self.valor_zona(zid, Z_FACTOR, DEFECTO_FACTOR_ZONA))
        bruto = (
            self.deficit(zid)
            + self._estado["et0_acumulada"] * self.kc(zid) * factor
            - self._lluvia_efectiva()
        )
        return min(max(bruto, 0.0), maximo)

    def duracion_estimada(self, zid: str, litros: int | None = None) -> timedelta:
        vol = self.volumen_objetivo(zid) if litros is None else litros
        if vol <= 0:
            return timedelta(0)
        return timedelta(hours=vol / max(self.caudal(zid), 1.0))

    # ── Planificación de la hora de inicio ────────────────────────────

    def _hora_inicio(self, amanecer: datetime) -> datetime:
        modo = self._opt(CONF_MODO_INICIO, MODO_FIN_AMANECER)
        desfase = timedelta(seconds=int(self._opt(CONF_DESFASE_ZONAS, DEFECTO_DESFASE_ZONAS)))

        if modo == MODO_HORA_FIJA:
            crudo = self._opt(CONF_HORA_FIJA, DEFECTO_HORA_FIJA)
            partes = dt_util.parse_time(crudo) or time(3, 0)
            local = dt_util.as_local(amanecer)
            inicio = local.replace(
                hour=partes.hour, minute=partes.minute, second=partes.second, microsecond=0
            )
            if inicio > local:
                inicio -= timedelta(days=1)
            return dt_util.as_utc(inicio)

        if modo == MODO_OFFSET_AMANECER:
            minutos = int(self._opt(CONF_OFFSET_AMANECER, DEFECTO_OFFSET_AMANECER))
            return amanecer + timedelta(minutes=minutos)

        # fin_amanecer: se estima cuánto dura el ciclo y se retrocede desde el
        # amanecer, de modo que el suelo quede recargado justo cuando la
        # planta empieza a transpirar.
        total = timedelta(0)
        for indice, z in enumerate(self.zonas):
            zid = z[Z_ID]
            litros = self.volumen_objetivo(zid, self._deficit_proyectado(zid))
            if litros <= 0:
                continue
            fin_zona = indice * desfase + self.duracion_estimada(zid, litros)
            total = max(total, fin_zona)

        margen = timedelta(minutes=int(self._opt(CONF_MARGEN_DURACION, DEFECTO_MARGEN_DURACION)))
        total = max(total + margen, timedelta(minutes=5))

        inicio = amanecer - total
        # Nunca antes de la hora mínima configurada de esa misma noche
        limite_crudo = dt_util.parse_time(self._opt(CONF_HORA_MINIMA, DEFECTO_HORA_MINIMA))
        if limite_crudo:
            local_amanecer = dt_util.as_local(amanecer)
            limite = local_amanecer.replace(
                hour=limite_crudo.hour,
                minute=limite_crudo.minute,
                second=0,
                microsecond=0,
            )
            if limite > local_amanecer:
                limite -= timedelta(days=1)
            inicio = max(inicio, dt_util.as_utc(limite))
        return inicio

    @callback
    def _planificar(self) -> None:
        """Programa el planificador y, si procede, el ciclo de esta noche."""
        if self._cancelar_planificador:
            self._cancelar_planificador()
            self._cancelar_planificador = None
        if self._cancelar_ciclo:
            self._cancelar_ciclo()
            self._cancelar_ciclo = None

        amanecer = get_astral_event_next(self.hass, "sunrise")
        if isinstance(amanecer, float):
            amanecer = dt_util.utc_from_timestamp(amanecer)

        ahora = dt_util.utcnow()

        # ¿Ya se ejecutó el ciclo que corresponde a este amanecer? Sin esta
        # comprobación, replanificar justo después de regar volvería a
        # programar un segundo ciclo antes del mismo amanecer.
        ya_ejecutado = False
        if marca := self._estado.get("ultimo_ciclo"):
            if (ultimo := dt_util.parse_datetime(marca)) is not None:
                ya_ejecutado = ultimo > amanecer - VENTANA_CICLO_CUMPLIDO

        self._proximo = None
        if not ya_ejecutado:
            inicio = self._hora_inicio(amanecer)
            if inicio <= ahora < amanecer:
                # HA arrancó dentro de la ventana y el ciclo no llegó a
                # ejecutarse: se lanza cuanto antes, aún de noche.
                inicio = ahora + timedelta(minutes=1)
            if inicio > ahora:
                self._proximo = inicio
                self._cancelar_ciclo = async_track_point_in_utc_time(
                    self.hass, self._disparar_ciclo, inicio
                )

        # Replanificación al entrar en la ventana del amanecer siguiente, para
        # recalcular la hora de arranque con los volúmenes ya actualizados.
        punto = amanecer - VENTANA_PLANIFICACION
        if punto <= ahora:
            punto = amanecer + timedelta(days=1) - VENTANA_PLANIFICACION
        self._cancelar_planificador = async_track_point_in_utc_time(
            self.hass, self._replanificar, punto
        )

    async def _replanificar(self, _ahora: datetime) -> None:
        self._planificar()
        await self.async_refresh()

    async def _disparar_ciclo(self, _ahora: datetime) -> None:
        self._cancelar_ciclo = None
        try:
            await self.ejecutar_ciclo()
        finally:
            self._planificar()
            await self.async_refresh()

    # ── Ejecución del ciclo ───────────────────────────────────────────

    async def ejecutar_ciclo(self, forzar_simulacion: bool | None = None) -> dict[str, Any]:
        """Aplica el balance hídrico y riega las zonas que lo pidan."""
        if self._ciclo_en_curso:
            _LOGGER.warning("Ciclo de riego ya en curso; se ignora la nueva ejecución")
            return {"resultado": "ya_en_curso"}
        self._ciclo_en_curso = True
        try:
            return await self._ejecutar_ciclo(forzar_simulacion)
        finally:
            self._ciclo_en_curso = False

    async def _ejecutar_ciclo(self, forzar_simulacion: bool | None = None) -> dict[str, Any]:
        simulacion = self.simulacion if forzar_simulacion is None else forzar_simulacion
        op = self.opciones
        resumen: dict[str, Any] = {"simulacion": simulacion, "zonas": {}}

        # 1. ET₀ del periodo y lluvia efectiva
        et0_periodo = float(self._estado["et0_acumulada"])
        lluvia = self._lluvia_efectiva()
        maximo = float(self._opt(CONF_DEFICIT_MAXIMO, DEFECTO_DEFICIT_MAXIMO))

        for z in self.zonas:
            zid = z[Z_ID]
            factor = float(self.valor_zona(zid, Z_FACTOR, DEFECTO_FACTOR_ZONA))
            nuevo = self.deficit(zid) + et0_periodo * self.kc(zid) * factor - lluvia
            self.runtime(zid)["deficit"] = round(min(max(nuevo, 0.0), maximo), 2)
            self.runtime(zid)["litros_hoy"] = 0.0

        self._estado["et0_periodo_anterior"] = round(et0_periodo, 2)
        self._estado["et0_acumulada"] = 0.0
        self._estado["ultimo_ciclo"] = dt_util.utcnow().isoformat()
        await self._guardar()

        resumen["et0_periodo"] = round(et0_periodo, 2)
        resumen["lluvia_efectiva"] = lluvia

        # 2. Protección por helada — el déficit se conserva
        temp = _num(self.hass.states.get(op[CONF_SENSOR_TEMP]), 99.0)
        umbral_helada = float(self._opt(CONF_TEMP_HELADA, DEFECTO_TEMP_HELADA))
        if temp < umbral_helada:
            await self._avisar(
                f"❄️ Riego pospuesto por helada. Temperatura {temp} °C. "
                "Los déficits se conservan para el próximo ciclo."
            )
            resumen["resultado"] = "helada"
            self._emitir("ciclo_omitido", resumen)
            await self.async_refresh()
            return resumen

        # 3. Aplazamiento por lluvia prevista, como máximo un día
        prevista = await self._lluvia_prevista()
        resumen["lluvia_prevista"] = prevista
        umbral_prevista = float(self._opt(CONF_LLUVIA_PREVISTA, DEFECTO_LLUVIA_PREVISTA))
        if prevista >= umbral_prevista and not self._estado.get("aplazado_lluvia"):
            self._estado["aplazado_lluvia"] = True
            await self._guardar()
            await self._avisar(
                f"🌧 Riego aplazado 24 h: {prevista} mm previstos. "
                "Los déficits se conservan; si no llueve, mañana se riega."
            )
            resumen["resultado"] = "aplazado_lluvia"
            self._emitir("ciclo_omitido", resumen)
            await self.async_refresh()
            return resumen

        self._estado["aplazado_lluvia"] = False
        await self._guardar()

        # 4. Riego zona a zona, con desfase fijo entre ellas
        desfase = int(self._opt(CONF_DESFASE_ZONAS, DEFECTO_DESFASE_ZONAS))
        primera = True
        for z in self.zonas:
            zid, nombre = z[Z_ID], z.get(Z_NOMBRE, z[Z_ID])
            litros = self.volumen_objetivo(zid)
            detalle = {"litros": litros, "deficit_previo": self.deficit(zid)}

            if litros <= 0:
                detalle["resultado"] = "sin_riego"
                resumen["zonas"][zid] = detalle
                continue

            if self._en_fallo(zid):
                estado = self.hass.states.get(z.get(Z_SENSOR_ESTADO) or "")
                detalle["resultado"] = "bloqueada"
                detalle["estado_valvula"] = estado.state if estado else "desconocido"
                resumen["zonas"][zid] = detalle
                await self._avisar(
                    f"⚠️ {nombre}: riego saltado, la válvula reporta "
                    f"{detalle['estado_valvula']}. El déficit "
                    f"({self.deficit(zid)} mm) se conserva."
                )
                continue

            if not primera and desfase > 0:
                await self._dormir(desfase)
            primera = False

            if not simulacion:
                await self._enviar(z, litros)

            m2 = float(self.valor_zona(zid, Z_M2, DEFECTO_M2))
            rt = self.runtime(zid)
            rt["deficit"] = round(max(self.deficit(zid) - litros / max(m2, 1.0), 0.0), 2)
            rt["litros_hoy"] = float(litros)
            rt["litros_temporada"] = round(float(rt.get("litros_temporada", 0.0)) + litros, 1)
            rt["ultimo_riego"] = dt_util.utcnow().isoformat()
            detalle["resultado"] = "simulado" if simulacion else "regado"
            detalle["deficit_posterior"] = rt["deficit"]
            resumen["zonas"][zid] = detalle

        await self._guardar()
        resumen.setdefault("resultado", "simulado" if simulacion else "completado")
        self._emitir("ciclo_completado", resumen)

        if simulacion:
            lineas = [
                f"· {(self.zona(z) or {}).get(Z_NOMBRE, z)}: {d['litros']} L ({d['resultado']})"
                for z, d in resumen["zonas"].items()
            ]
            await self._avisar(
                "🧪 SIMULACIÓN de riego (no se ha enviado nada a las válvulas)\n"
                f"ET₀ del periodo: {resumen['et0_periodo']} mm · "
                f"lluvia efectiva: {lluvia} mm\n" + "\n".join(lineas)
            )

        await self.async_refresh()
        return resumen

    async def _dormir(self, segundos: int) -> None:
        await asyncio.sleep(segundos)

    def _en_fallo(self, zid: str) -> bool:
        cfg = self.zona(zid) or {}
        ent = cfg.get(Z_SENSOR_ESTADO)
        if not ent:
            return False
        estado = self.hass.states.get(ent)
        return estado is not None and estado.state in ESTADOS_FALLO

    async def _enviar(self, zona: dict[str, Any], litros: int) -> None:
        """Publica la orden de riego volumétrico en el topic de la zona.

        La electroválvula ejecuta la dosis de forma autónoma: si Home Assistant
        se reinicia o Zigbee se cae a mitad de riego, la válvula termina y
        cierra sola. Por eso no se espera confirmación.
        """
        topic = zona.get(Z_TOPIC)
        if not topic:
            _LOGGER.error("La zona %s no tiene topic MQTT configurado", zona.get(Z_NOMBRE))
            return
        payload = json.dumps(
            {
                "cyclic_quantitative_irrigation": {
                    "total_number": 1,
                    "irrigation_capacity": int(litros),
                    "irrigation_interval": 0,
                }
            }
        )
        await mqtt.async_publish(self.hass, topic, payload)
        _LOGGER.info("Riego %s: %s L enviados a %s", zona.get(Z_NOMBRE), litros, topic)

    # ── Servicios auxiliares ──────────────────────────────────────────

    async def regar_zona(self, zid: str, litros: int) -> None:
        zona = self.zona(zid)
        if zona is None:
            raise ValueError(f"Zona desconocida: {zid}")
        if self.simulacion:
            await self._avisar(f"🧪 SIMULACIÓN: {zona.get(Z_NOMBRE)} habría recibido {litros} L")
            return
        await self._enviar(zona, litros)
        rt = self.runtime(zid)
        rt["litros_hoy"] = float(rt.get("litros_hoy", 0.0)) + litros
        rt["litros_temporada"] = round(float(rt.get("litros_temporada", 0.0)) + litros, 1)
        rt["ultimo_riego"] = dt_util.utcnow().isoformat()
        await self._guardar()
        await self.async_refresh()

    async def ajustar_deficit(self, zid: str, valor: float, relativo: bool) -> None:
        maximo = float(self._opt(CONF_DEFICIT_MAXIMO, DEFECTO_DEFICIT_MAXIMO))
        actual = self.deficit(zid)
        nuevo = actual + valor if relativo else valor
        self.runtime(zid)["deficit"] = round(min(max(nuevo, 0.0), maximo), 2)
        await self._guardar()
        await self.async_refresh()
        self._planificar()

    async def reiniciar_temporada(self) -> None:
        for z in self.zonas:
            self.runtime(z[Z_ID])["litros_temporada"] = 0.0
        await self._guardar()
        await self.async_refresh()

    async def saltar_dia(self) -> None:
        self._estado["aplazado_lluvia"] = True
        await self._guardar()
        await self.async_refresh()

    # ── Avisos ────────────────────────────────────────────────────────

    def _emitir(self, tipo: str, datos: dict[str, Any]) -> None:
        self.hass.bus.async_fire(EVENTO, {"tipo": tipo, **datos})

    async def _avisar(self, mensaje: str) -> None:
        _LOGGER.info("Riego: %s", mensaje)
        destino = self.opciones.get(CONF_NOTIFY)
        if not destino:
            return
        try:
            await self.hass.services.async_call(
                "notify",
                "send_message",
                {"entity_id": destino, "message": mensaje},
                blocking=False,
            )
        except Exception:  # noqa: BLE001 - un fallo de aviso no debe parar el riego
            _LOGGER.warning("No se pudo notificar a %s", destino, exc_info=True)

    # ── Datos para las entidades ──────────────────────────────────────

    async def _async_update_data(self) -> dict[str, Any]:
        resultado = self._et0_instantanea()
        amanecer = get_astral_event_next(self.hass, "sunrise")
        if isinstance(amanecer, float):
            amanecer = dt_util.utc_from_timestamp(amanecer)

        zonas: dict[str, Any] = {}
        for z in self.zonas:
            zid = z[Z_ID]
            deficit = self.deficit(zid)
            umbral = float(self.valor_zona(zid, Z_UMBRAL, DEFECTO_UMBRAL))
            litros = self.volumen_objetivo(zid)
            bloqueada = self._en_fallo(zid)

            if not self.habilitada(zid):
                estado = ESTADO_DESHABILITADA
            elif bloqueada:
                estado = ESTADO_BLOQUEADA
            elif self._regando(zid):
                estado = ESTADO_REGANDO
            elif deficit >= umbral:
                estado = ESTADO_LISTA
            else:
                estado = ESTADO_ACUMULANDO

            zonas[zid] = {
                "nombre": z.get(Z_NOMBRE, zid),
                "deficit": round(deficit, 2),
                "falta": round(max(umbral - deficit, 0.0), 2),
                "umbral": umbral,
                "volumen": litros,
                "kc": round(self.kc(zid), 3),
                "m2": float(self.valor_zona(zid, Z_M2, DEFECTO_M2)),
                "techo": float(self.valor_zona(zid, Z_TECHO, DEFECTO_TECHO)),
                "factor": float(self.valor_zona(zid, Z_FACTOR, DEFECTO_FACTOR_ZONA)),
                "habilitada": self.habilitada(zid),
                "bloqueada": bloqueada,
                "estado": estado,
                "caudal": self.caudal(zid),
                "duracion_min": round(
                    self.duracion_estimada(zid, litros).total_seconds() / 60, 1
                ),
                "litros_hoy": float(self.runtime(zid).get("litros_hoy", 0.0)),
                "litros_temporada": float(self.runtime(zid).get("litros_temporada", 0.0)),
                "ultimo_riego": self.runtime(zid).get("ultimo_riego"),
            }

        return {
            "et0_instantanea": round(resultado.et0, 3) if resultado else None,
            "et0_detalle": {
                "ra_mj_h": round(resultado.ra, 3),
                "rso_mj_h": round(resultado.rso, 3),
                "rn_mj_h": round(resultado.rn, 3),
                "f_cd": round(resultado.f_cd, 3),
                "u2_ms": round(resultado.u2, 3),
                "termino_radiativo": round(resultado.termino_radiativo, 4),
                "termino_aerodinamico": round(resultado.termino_aerodinamico, 4),
            }
            if resultado
            else {},
            "et0_acumulada": round(self._estado["et0_acumulada"], 3),
            "et0_periodo_anterior": self._estado["et0_periodo_anterior"],
            "lluvia_efectiva": self._lluvia_efectiva(),
            "aplazado_lluvia": bool(self._estado.get("aplazado_lluvia")),
            "simulacion": self.simulacion,
            "proximo_ciclo": self._proximo,
            "ultimo_ciclo": self._estado.get("ultimo_ciclo"),
            "amanecer": amanecer,
            "zonas": zonas,
        }

    def _regando(self, zid: str) -> bool:
        cfg = self.zona(zid) or {}
        ent = cfg.get(Z_SENSOR_CAUDAL)
        if not ent:
            return False
        return _num(self.hass.states.get(ent), 0.0) > 0
