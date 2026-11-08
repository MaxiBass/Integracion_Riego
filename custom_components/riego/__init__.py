"""Riego por Balance Hídrico — integración personalizada de Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, Z_ID
from .entity import DISPOSITIVO_SISTEMA
from .coordinator import RiegoCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type RiegoConfigEntry = ConfigEntry[RiegoCoordinator]

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Entidades que la integración tuvo y ya no publica. Se borran del registro
# al arrancar; si no, quedarían para siempre como «ya no las proporciona la
# integración».
# - Los number, en v0.5.0: los ajustes se cambian solo en «Configurar» (§7.25).
# - binary_sensor.<zona>_bloqueada, en v0.6.0: el estado de la válvula ya no
#   bloquea el riego (§7.28).
PLATAFORMAS_RETIRADAS = ("number",)
ENTIDADES_RETIRADAS = (("binary_sensor", "_bloqueada"),)

RUTA_ESTATICA = "/riego_static"
FICHERO_ESTRATEGIA = "riego-strategy.js"

SERVICIO_EJECUTAR = "ejecutar_ciclo"
SERVICIO_REGAR = "regar_zona"
SERVICIO_DEFICIT = "ajustar_deficit"
SERVICIO_SALTAR = "saltar_dia"
SERVICIO_TEMPORADA = "reiniciar_temporada"

ESQUEMA_EJECUTAR = vol.Schema({vol.Optional("simulacion"): cv.boolean})
ESQUEMA_REGAR = vol.Schema(
    {
        vol.Required("zona"): cv.string,
        vol.Required("litros"): vol.All(vol.Coerce(int), vol.Range(min=1, max=5000)),
    }
)
ESQUEMA_DEFICIT = vol.Schema(
    {
        vol.Required("zona"): cv.string,
        # Mismos límites que el selector de services.yaml
        vol.Required("valor"): vol.All(vol.Coerce(float), vol.Range(min=-50, max=50)),
        vol.Optional("relativo", default=False): cv.boolean,
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registra los servicios una vez, con o sin entrada configurada."""
    _registrar_servicios(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: RiegoConfigEntry) -> bool:
    """Configura una entrada de la integración."""
    _borrar_entidades_retiradas(hass, entry)
    _borrar_zonas_eliminadas(hass, entry)
    coordinador = RiegoCoordinator(hass, entry)
    await coordinador.async_iniciar()

    # El dispositivo de sistema se crea aquí, antes que las plataformas, para
    # que las zonas puedan colgar de él con via_device_id.
    dispositivo = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, DISPOSITIVO_SISTEMA)},
        name="Balance Hídrico",
        manufacturer="Riego",
        model="Balance hídrico FAO-56",
    )
    coordinador.id_dispositivo_sistema = dispositivo.id

    entry.runtime_data = coordinador
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await _registrar_frontend(hass)

    entry.async_on_unload(entry.add_update_listener(_al_actualizar_opciones))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: RiegoConfigEntry) -> bool:
    """Descarga una entrada. También al recargarla tras un cambio en Configurar."""
    descargada = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if descargada:
        # Cancela el ciclo en curso y espera a que suelte el almacén antes de
        # que el coordinador de la recarga lo lea (§7.29).
        await entry.runtime_data.async_parar()
    return descargada


def _borrar_entidades_retiradas(hass: HomeAssistant, entry: ConfigEntry) -> None:
    registro = er.async_get(hass)
    for entidad in er.async_entries_for_config_entry(registro, entry.entry_id):
        if entidad.domain in PLATAFORMAS_RETIRADAS or any(
            entidad.domain == dominio and str(entidad.unique_id).endswith(sufijo)
            for dominio, sufijo in ENTIDADES_RETIRADAS
        ):
            _LOGGER.info("Se retira %s: ya no la publica la integración", entidad.entity_id)
            registro.async_remove(entidad.entity_id)


def _borrar_zonas_eliminadas(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Quita del registro los dispositivos y entidades de las zonas borradas.

    Borrar una zona en Configurar recarga la entrada; sin esto, sus entidades
    se quedaban como «ya no las proporciona la integración».
    """
    opciones = {**entry.data, **entry.options}
    vigentes = {f"zona_{z[Z_ID]}" for z in opciones.get("zonas", [])}
    dispositivos = dr.async_get(hass)
    entidades = er.async_get(hass)
    for dispositivo in dr.async_entries_for_config_entry(dispositivos, entry.entry_id):
        zonas = [i for d, i in dispositivo.identifiers if d == DOMAIN and i.startswith("zona_")]
        if not zonas or zonas[0] in vigentes:
            continue
        for entidad in er.async_entries_for_device(
            entidades, dispositivo.id, include_disabled_entities=True
        ):
            entidades.async_remove(entidad.entity_id)
        _LOGGER.info("Se retira el dispositivo de la zona borrada %s", dispositivo.name)
        dispositivos.async_remove_device(dispositivo.id)


async def _al_actualizar_opciones(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarga la entrada cuando cambia la configuración estructural."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _registrar_frontend(hass: HomeAssistant) -> None:
    """Sirve la estrategia de panel y la añade a los módulos del frontend."""
    if hass.data.get(f"{DOMAIN}_frontend"):
        return
    origen = Path(__file__).parent / "frontend" / FICHERO_ESTRATEGIA
    if not origen.exists():
        _LOGGER.warning("No se encontró %s; el panel automático no estará disponible", origen)
        return
    await hass.http.async_register_static_paths(
        [
            StaticPathConfig(
                f"{RUTA_ESTATICA}/{FICHERO_ESTRATEGIA}", str(origen), cache_headers=False
            )
        ]
    )
    from homeassistant.components.frontend import add_extra_js_url

    add_extra_js_url(hass, f"{RUTA_ESTATICA}/{FICHERO_ESTRATEGIA}")
    hass.data[f"{DOMAIN}_frontend"] = True


def _coordinador(hass: HomeAssistant) -> RiegoCoordinator:
    entradas = hass.config_entries.async_loaded_entries(DOMAIN)
    if not entradas:
        raise ServiceValidationError("La integración Riego no está configurada o no ha cargado")
    return entradas[0].runtime_data


def _resolver_zona(coordinador: RiegoCoordinator, referencia: str) -> str:
    """Acepta el id interno o el nombre visible de la zona."""
    referencia_norm = referencia.strip().lower()
    for zona in coordinador.zonas:
        if zona[Z_ID].lower() == referencia_norm:
            return zona[Z_ID]
        if str(zona.get("nombre", "")).lower() == referencia_norm:
            return zona[Z_ID]
    raise ServiceValidationError(f"Zona desconocida: {referencia}")


def _registrar_servicios(hass: HomeAssistant) -> None:
    async def ejecutar(call: ServiceCall) -> dict:
        coordinador = _coordinador(hass)
        return await coordinador.ejecutar_ciclo(call.data.get("simulacion"))

    async def regar(call: ServiceCall) -> None:
        coordinador = _coordinador(hass)
        zid = _resolver_zona(coordinador, call.data["zona"])
        await coordinador.regar_zona(zid, call.data["litros"])

    async def deficit(call: ServiceCall) -> None:
        coordinador = _coordinador(hass)
        zid = _resolver_zona(coordinador, call.data["zona"])
        await coordinador.ajustar_deficit(zid, call.data["valor"], call.data["relativo"])

    async def saltar(_call: ServiceCall) -> None:
        await _coordinador(hass).set_saltar_proximo(True)

    async def temporada(_call: ServiceCall) -> None:
        await _coordinador(hass).reiniciar_temporada()

    hass.services.async_register(
        DOMAIN,
        SERVICIO_EJECUTAR,
        ejecutar,
        schema=ESQUEMA_EJECUTAR,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICIO_REGAR, regar, schema=ESQUEMA_REGAR)
    hass.services.async_register(DOMAIN, SERVICIO_DEFICIT, deficit, schema=ESQUEMA_DEFICIT)
    hass.services.async_register(DOMAIN, SERVICIO_SALTAR, saltar)
    hass.services.async_register(DOMAIN, SERVICIO_TEMPORADA, temporada)
