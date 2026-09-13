"""Interruptores de Riego: simulación global y habilitación por zona."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
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
    entidades: list[SwitchEntity] = [ModoSimulacion(coordinador)]
    for zona in coordinador.zonas:
        entidades.append(
            ZonaHabilitada(coordinador, zona[Z_ID], zona.get(Z_NOMBRE, zona[Z_ID]))
        )
    async_add_entities(entidades)


class ModoSimulacion(EntidadSistema, SwitchEntity):
    """Mientras está activo se calcula todo pero no se envía nada a las válvulas."""

    _attr_name = "Modo simulación"
    _attr_icon = "mdi:flask-outline"

    def __init__(self, coordinador: RiegoCoordinator) -> None:
        super().__init__(coordinador, "simulacion")

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("simulacion"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_simulacion(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_simulacion(False)


class ZonaHabilitada(EntidadZona, SwitchEntity):
    _attr_name = "Habilitada"
    _attr_icon = "mdi:toggle-switch"

    def __init__(self, coordinador: RiegoCoordinator, zid: str, nombre: str) -> None:
        super().__init__(coordinador, zid, nombre, "habilitada")

    @property
    def is_on(self) -> bool:
        return bool(self._zona.get("habilitada"))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_valor_zona(self._zid, "habilitada", True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_valor_zona(self._zid, "habilitada", False)
