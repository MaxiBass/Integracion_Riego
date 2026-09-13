"""Flujo de configuración de Riego por Balance Hídrico."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.util import slugify

from .const import (
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
    FORECAST_DIARIO,
    FORECAST_HORARIO,
    MODO_FIN_AMANECER,
    MODO_HORA_FIJA,
    MODO_OFFSET_AMANECER,
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


def _sensor(dominios: list[str] | str = "sensor") -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=dominios))


def _numero(
    minimo: float, maximo: float, paso: float, unidad: str | None = None
) -> selector.NumberSelector:
    # unit_of_measurement solo se incluye si hay unidad: el esquema del
    # selector exige str y rechaza None.
    config = selector.NumberSelectorConfig(
        min=minimo,
        max=maximo,
        step=paso,
        mode=selector.NumberSelectorMode.BOX,
    )
    if unidad:
        config["unit_of_measurement"] = unidad
    return selector.NumberSelector(config)


def esquema_meteo(valores: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_SENSOR_TEMP, default=valores.get(CONF_SENSOR_TEMP)): _sensor(),
            vol.Required(
                CONF_SENSOR_HUMEDAD, default=valores.get(CONF_SENSOR_HUMEDAD)
            ): _sensor(),
            vol.Required(
                CONF_SENSOR_RADIACION, default=valores.get(CONF_SENSOR_RADIACION)
            ): _sensor(),
            vol.Optional(
                CONF_SENSOR_VIENTO, description={"suggested_value": valores.get(CONF_SENSOR_VIENTO)}
            ): _sensor(),
            vol.Optional(
                CONF_SENSOR_PRESION,
                description={"suggested_value": valores.get(CONF_SENSOR_PRESION)},
            ): _sensor(),
            vol.Optional(
                CONF_SENSOR_LLUVIA, description={"suggested_value": valores.get(CONF_SENSOR_LLUVIA)}
            ): _sensor(),
            vol.Required(
                CONF_ALTURA_ANEMOMETRO,
                default=valores.get(CONF_ALTURA_ANEMOMETRO, DEFECTO_ALTURA_ANEMOMETRO),
            ): _numero(1, 30, 0.5, "m"),
            vol.Required(
                CONF_VIENTO_MINIMO,
                default=valores.get(CONF_VIENTO_MINIMO, DEFECTO_VIENTO_MINIMO),
            ): _numero(0, 2, 0.1, "m/s"),
            vol.Required(
                CONF_FACTOR_RADIACION,
                default=valores.get(CONF_FACTOR_RADIACION, DEFECTO_FACTOR_RADIACION),
            ): _numero(0.5, 1.5, 0.01),
        }
    )


def esquema_prevision(valores: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_WEATHER, description={"suggested_value": valores.get(CONF_WEATHER)}
            ): _sensor("weather"),
            vol.Required(
                CONF_FORECAST_TIPO, default=valores.get(CONF_FORECAST_TIPO, FORECAST_HORARIO)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[FORECAST_HORARIO, FORECAST_DIARIO],
                    translation_key="forecast_tipo",
                )
            ),
            vol.Required(
                CONF_FORECAST_HORAS,
                default=valores.get(CONF_FORECAST_HORAS, DEFECTO_FORECAST_HORAS),
            ): _numero(1, 120, 1, "h"),
            vol.Required(
                CONF_LLUVIA_PREVISTA,
                default=valores.get(CONF_LLUVIA_PREVISTA, DEFECTO_LLUVIA_PREVISTA),
            ): _numero(0.5, 50, 0.5, "mm"),
            vol.Required(
                CONF_LLUVIA_MINIMA, default=valores.get(CONF_LLUVIA_MINIMA, DEFECTO_LLUVIA_MINIMA)
            ): _numero(0, 20, 0.1, "mm"),
            vol.Required(
                CONF_LLUVIA_CAP, default=valores.get(CONF_LLUVIA_CAP, DEFECTO_LLUVIA_CAP)
            ): _numero(1, 200, 1, "mm"),
            vol.Required(
                CONF_TEMP_HELADA, default=valores.get(CONF_TEMP_HELADA, DEFECTO_TEMP_HELADA)
            ): _numero(-10, 10, 0.5, "°C"),
        }
    )


def esquema_ciclo(valores: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_MODO_INICIO, default=valores.get(CONF_MODO_INICIO, MODO_FIN_AMANECER)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[MODO_FIN_AMANECER, MODO_OFFSET_AMANECER, MODO_HORA_FIJA],
                    translation_key="modo_inicio",
                )
            ),
            vol.Required(
                CONF_OFFSET_AMANECER,
                default=valores.get(CONF_OFFSET_AMANECER, DEFECTO_OFFSET_AMANECER),
            ): _numero(-240, 240, 5, "min"),
            vol.Required(
                CONF_HORA_FIJA, default=valores.get(CONF_HORA_FIJA, DEFECTO_HORA_FIJA)
            ): selector.TimeSelector(),
            vol.Required(
                CONF_HORA_MINIMA, default=valores.get(CONF_HORA_MINIMA, DEFECTO_HORA_MINIMA)
            ): selector.TimeSelector(),
            vol.Required(
                CONF_MARGEN_DURACION,
                default=valores.get(CONF_MARGEN_DURACION, DEFECTO_MARGEN_DURACION),
            ): _numero(0, 120, 5, "min"),
            vol.Required(
                CONF_DESFASE_ZONAS, default=valores.get(CONF_DESFASE_ZONAS, DEFECTO_DESFASE_ZONAS)
            ): _numero(0, 7200, 10, "s"),
            vol.Required(
                CONF_DEFICIT_MAXIMO,
                default=valores.get(CONF_DEFICIT_MAXIMO, DEFECTO_DEFICIT_MAXIMO),
            ): _numero(5, 200, 1, "mm"),
            vol.Required(
                CONF_SIMULACION, default=valores.get(CONF_SIMULACION, True)
            ): selector.BooleanSelector(),
            vol.Optional(
                CONF_NOTIFY, description={"suggested_value": valores.get(CONF_NOTIFY)}
            ): _sensor("notify"),
        }
    )


def esquema_zona(valores: dict[str, Any]) -> vol.Schema:
    kc = valores.get(Z_KC) or DEFECTO_KC
    return vol.Schema(
        {
            vol.Required(Z_NOMBRE, default=valores.get(Z_NOMBRE, "")): selector.TextSelector(),
            vol.Required(Z_M2, default=valores.get(Z_M2, DEFECTO_M2)): _numero(1, 10000, 1, "m²"),
            vol.Required(Z_UMBRAL, default=valores.get(Z_UMBRAL, DEFECTO_UMBRAL)): _numero(
                0.1, 30, 0.1, "mm"
            ),
            vol.Required(Z_TECHO, default=valores.get(Z_TECHO, DEFECTO_TECHO)): _numero(
                10, 10000, 10, "L"
            ),
            vol.Required(Z_FACTOR, default=valores.get(Z_FACTOR, DEFECTO_FACTOR_ZONA)): _numero(
                0.1, 2.0, 0.05
            ),
            vol.Required(Z_KC, default=", ".join(str(v) for v in kc)): selector.TextSelector(),
            vol.Required(Z_TOPIC, default=valores.get(Z_TOPIC, "")): selector.TextSelector(),
            vol.Required(
                Z_CAUDAL_DEFECTO, default=valores.get(Z_CAUDAL_DEFECTO, DEFECTO_CAUDAL)
            ): _numero(10, 5000, 10, "L/h"),
            vol.Optional(
                Z_SENSOR_ESTADO, description={"suggested_value": valores.get(Z_SENSOR_ESTADO)}
            ): _sensor(),
            vol.Optional(
                Z_SENSOR_CAUDAL, description={"suggested_value": valores.get(Z_SENSOR_CAUDAL)}
            ): _sensor(),
            vol.Optional(
                Z_SENSOR_VOLUMEN, description={"suggested_value": valores.get(Z_SENSOR_VOLUMEN)}
            ): _sensor(),
            vol.Optional(
                Z_SENSOR_DURACION, description={"suggested_value": valores.get(Z_SENSOR_DURACION)}
            ): _sensor(),
        }
    )


def _normalizar_zona(datos: dict[str, Any], zid: str | None = None) -> tuple[dict, dict]:
    """Valida y normaliza el formulario de una zona. Devuelve (zona, errores)."""
    errores: dict[str, str] = {}
    zona = dict(datos)

    crudo = str(zona.get(Z_KC, "")).replace(";", ",")
    try:
        valores = [float(p.strip()) for p in crudo.split(",") if p.strip()]
    except ValueError:
        valores = []
    if len(valores) != 12 or any(not 0 <= v <= 3 for v in valores):
        errores[Z_KC] = "kc_invalido"
    else:
        zona[Z_KC] = valores

    nombre = str(zona.get(Z_NOMBRE, "")).strip()
    if not nombre:
        errores[Z_NOMBRE] = "nombre_requerido"
    if not str(zona.get(Z_TOPIC, "")).strip():
        errores[Z_TOPIC] = "topic_requerido"

    zona[Z_ID] = zid or slugify(nombre) or "zona"
    return zona, errores


class RiegoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Alta inicial: meteorología, previsión, ciclo y primera zona."""

    VERSION = 1

    def __init__(self) -> None:
        self._datos: dict[str, Any] = {}

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            self._datos.update(user_input)
            return await self.async_step_prevision()
        return self.async_show_form(step_id="user", data_schema=esquema_meteo({}))

    async def async_step_prevision(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._datos.update(user_input)
            return await self.async_step_ciclo()
        return self.async_show_form(step_id="prevision", data_schema=esquema_prevision({}))

    async def async_step_ciclo(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            self._datos.update(user_input)
            self._datos[CONF_ZONAS] = []
            return await self.async_step_zona()
        return self.async_show_form(step_id="ciclo", data_schema=esquema_ciclo({}))

    async def async_step_zona(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            zona, errores = _normalizar_zona(user_input)
            if errores:
                return self.async_show_form(
                    step_id="zona", data_schema=esquema_zona(user_input), errors=errores
                )
            self._datos[CONF_ZONAS].append(zona)
            return await self.async_step_otra()
        return self.async_show_form(step_id="zona", data_schema=esquema_zona({}))

    async def async_step_otra(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            if user_input.get("añadir_otra"):
                return await self.async_step_zona()
            return self.async_create_entry(title="Riego", data=self._datos)
        return self.async_show_form(
            step_id="otra",
            data_schema=vol.Schema({vol.Required("añadir_otra", default=False): bool}),
            description_placeholders={
                "zonas": ", ".join(z[Z_NOMBRE] for z in self._datos[CONF_ZONAS])
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return RiegoOptionsFlow()


class RiegoOptionsFlow(OptionsFlow):
    """Permite reconfigurar cualquier sensor, parámetro o zona."""

    def __init__(self) -> None:
        self._zona_editada: str | None = None

    @property
    def _valores(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["meteo", "prevision", "ciclo", "zonas"],
        )

    async def _guardar(self, cambios: dict[str, Any]) -> ConfigFlowResult:
        nuevas = {**self.config_entry.options, **cambios}
        return self.async_create_entry(title="", data=nuevas)

    async def async_step_meteo(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._guardar(user_input)
        return self.async_show_form(step_id="meteo", data_schema=esquema_meteo(self._valores))

    async def async_step_prevision(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._guardar(user_input)
        return self.async_show_form(
            step_id="prevision", data_schema=esquema_prevision(self._valores)
        )

    async def async_step_ciclo(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            return await self._guardar(user_input)
        return self.async_show_form(step_id="ciclo", data_schema=esquema_ciclo(self._valores))

    # ── Zonas ─────────────────────────────────────────────────────────

    async def async_step_zonas(self, user_input=None) -> ConfigFlowResult:
        zonas = self._valores.get(CONF_ZONAS, [])
        opciones = {z[Z_ID]: z.get(Z_NOMBRE, z[Z_ID]) for z in zonas}
        opciones["__nueva__"] = "➕ Añadir zona nueva"

        if user_input is not None:
            eleccion = user_input["zona"]
            if eleccion == "__nueva__":
                self._zona_editada = None
                return await self.async_step_editar_zona()
            self._zona_editada = eleccion
            return await self.async_step_editar_zona()

        return self.async_show_form(
            step_id="zonas",
            data_schema=vol.Schema(
                {
                    vol.Required("zona"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                selector.SelectOptionDict(value=k, label=v)
                                for k, v in opciones.items()
                            ]
                        )
                    )
                }
            ),
        )

    async def async_step_editar_zona(self, user_input=None) -> ConfigFlowResult:
        zonas = list(self._valores.get(CONF_ZONAS, []))
        actual = next((z for z in zonas if z[Z_ID] == self._zona_editada), {})

        if user_input is not None:
            if user_input.pop("eliminar", False) and self._zona_editada:
                zonas = [z for z in zonas if z[Z_ID] != self._zona_editada]
                return await self._guardar({CONF_ZONAS: zonas})

            zona, errores = _normalizar_zona(user_input, self._zona_editada)
            if errores:
                esquema = esquema_zona(user_input).extend(
                    {vol.Optional("eliminar", default=False): bool}
                )
                return self.async_show_form(
                    step_id="editar_zona", data_schema=esquema, errors=errores
                )
            if self._zona_editada:
                zonas = [zona if z[Z_ID] == self._zona_editada else z for z in zonas]
            else:
                if any(z[Z_ID] == zona[Z_ID] for z in zonas):
                    esquema = esquema_zona(user_input).extend(
                        {vol.Optional("eliminar", default=False): bool}
                    )
                    return self.async_show_form(
                        step_id="editar_zona",
                        data_schema=esquema,
                        errors={Z_NOMBRE: "zona_duplicada"},
                    )
                zonas.append(zona)
            return await self._guardar({CONF_ZONAS: zonas})

        esquema = esquema_zona(actual)
        if self._zona_editada:
            esquema = esquema.extend({vol.Optional("eliminar", default=False): bool})
        return self.async_show_form(step_id="editar_zona", data_schema=esquema)
