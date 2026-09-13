"""Base común de las entidades de Riego."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RiegoCoordinator

DISPOSITIVO_SISTEMA = "sistema"


def info_sistema() -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, DISPOSITIVO_SISTEMA)},
        name="Balance Hídrico",
        manufacturer="Riego",
        model="Balance hídrico FAO-56",
        entry_type=None,
    )


def info_zona(zid: str, nombre: str) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, f"zona_{zid}")},
        name=f"Zona {nombre}",
        manufacturer="Riego",
        model="Zona de riego",
        via_device=(DOMAIN, DISPOSITIVO_SISTEMA),
    )


class EntidadSistema(CoordinatorEntity[RiegoCoordinator]):
    """Entidad asociada al sistema completo."""

    _attr_has_entity_name = True

    def __init__(self, coordinador: RiegoCoordinator, clave: str) -> None:
        super().__init__(coordinador)
        self._clave = clave
        self._attr_unique_id = f"{coordinador.entry.entry_id}_{clave}"
        self._attr_device_info = info_sistema()


class EntidadZona(CoordinatorEntity[RiegoCoordinator]):
    """Entidad asociada a una zona concreta."""

    _attr_has_entity_name = True

    def __init__(self, coordinador: RiegoCoordinator, zid: str, nombre: str, clave: str) -> None:
        super().__init__(coordinador)
        self._zid = zid
        self._clave = clave
        self._attr_unique_id = f"{coordinador.entry.entry_id}_{zid}_{clave}"
        self._attr_device_info = info_zona(zid, nombre)

    @property
    def _zona(self) -> dict[str, Any]:
        return (self.coordinator.data or {}).get("zonas", {}).get(self._zid, {})

    @property
    def available(self) -> bool:
        return super().available and bool(self._zona)
