"""Sensores binarios de Riego."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, Z_ID, Z_NOMBRE
from .coordinator import RiegoCoordinator
from .entity import EntidadSistema, EntidadZona


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinador: RiegoCoordinator = hass.data[DOMAIN][entry.entry_id]
    entidades: list[BinarySensorEntity] = [AplazadoPorLluvia(coordinador)]
    for zona in coordinador.zonas:
        entidades.append(
            ZonaBloqueada(coordinador, zona[Z_ID], zona.get(Z_NOMBRE, zona[Z_ID]))
        )
        entidades.append(ZonaRegando(coordinador, zona[Z_ID], zona.get(Z_NOMBRE, zona[Z_ID])))
    async_add_entities(entidades)


class AplazadoPorLluvia(EntidadSistema, BinarySensorEntity):
    _attr_name = "Aplazado por lluvia prevista"
    _attr_icon = "mdi:weather-cloudy-clock"

    def __init__(self, coordinador: RiegoCoordinator) -> None:
        super().__init__(coordinador, "aplazado_lluvia")

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("aplazado_lluvia"))


class ZonaBloqueada(EntidadZona, BinarySensorEntity):
    _attr_name = "Bloqueada"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinador: RiegoCoordinator, zid: str, nombre: str) -> None:
        super().__init__(coordinador, zid, nombre, "bloqueada")

    @property
    def is_on(self) -> bool:
        return bool(self._zona.get("bloqueada"))


class ZonaRegando(EntidadZona, BinarySensorEntity):
    _attr_name = "Regando"
    _attr_device_class = BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:sprinkler-variant"

    def __init__(self, coordinador: RiegoCoordinator, zid: str, nombre: str) -> None:
        super().__init__(coordinador, zid, nombre, "regando")

    @property
    def is_on(self) -> bool:
        return self._zona.get("estado") == "regando"
