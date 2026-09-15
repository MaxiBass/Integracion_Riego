"""Riego por Balance Hídrico — integración personalizada de Home Assistant."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, Z_ID
from .entity import DISPOSITIVO_SISTEMA
from .coordinator import RiegoCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]

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
        vol.Required("valor"): vol.Coerce(float),
        vol.Optional("relativo", default=False): cv.boolean,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura una entrada de la integración."""
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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinador
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await _registrar_frontend(hass)
    _registrar_servicios(hass)

    entry.async_on_unload(entry.add_update_listener(_al_actualizar_opciones))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga una entrada."""
    descargada = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if descargada:
        coordinador: RiegoCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinador.async_parar()
        if not hass.data[DOMAIN]:
            for servicio in (
                SERVICIO_EJECUTAR,
                SERVICIO_REGAR,
                SERVICIO_DEFICIT,
                SERVICIO_SALTAR,
                SERVICIO_TEMPORADA,
            ):
                hass.services.async_remove(DOMAIN, servicio)
    return descargada


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
    datos = hass.data.get(DOMAIN) or {}
    if not datos:
        raise ValueError("La integración Riego no está configurada")
    return next(iter(datos.values()))


def _resolver_zona(coordinador: RiegoCoordinator, referencia: str) -> str:
    """Acepta el id interno o el nombre visible de la zona."""
    referencia_norm = referencia.strip().lower()
    for zona in coordinador.zonas:
        if zona[Z_ID].lower() == referencia_norm:
            return zona[Z_ID]
        if str(zona.get("nombre", "")).lower() == referencia_norm:
            return zona[Z_ID]
    raise ValueError(f"Zona desconocida: {referencia}")


def _registrar_servicios(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICIO_EJECUTAR):
        return

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
        await _coordinador(hass).saltar_dia()

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
