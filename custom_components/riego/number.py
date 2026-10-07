"""Parámetros ajustables en caliente: los de cada zona y la probabilidad de lluvia."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DEFECTO_FACTOR_ZONA,
    DEFECTO_PROBABILIDAD_PREVISTA,
    DEFECTO_M2,
    DEFECTO_TECHO,
    DEFECTO_UMBRAL,
    DOMAIN,
    Z_FACTOR,
    Z_ID,
    Z_M2,
    Z_NOMBRE,
    Z_TECHO,
    Z_UMBRAL,
)
from .coordinator import RiegoCoordinator
from .entity import EntidadSistema, EntidadZona


@dataclass(frozen=True, kw_only=True)
class DescripcionNumero(NumberEntityDescription):
    clave_zona: str
    defecto: float


# Los rangos se mantienen ajustados a lo verosímil: un rango enorme deja el
# deslizable de la interfaz inservible para valores pequeños (un umbral de
# 0,5 sobre 0-30 cae en el 1,6 % del recorrido).
NUMEROS: tuple[DescripcionNumero, ...] = (
    DescripcionNumero(
        key="superficie",
        name="Superficie",
        icon="mdi:ruler-square",
        native_unit_of_measurement="m²",
        native_min_value=1,
        native_max_value=2000,
        native_step=1,
        mode=NumberMode.BOX,
        clave_zona=Z_M2,
        defecto=DEFECTO_M2,
    ),
    DescripcionNumero(
        key="umbral",
        name="Umbral de riego",
        icon="mdi:water-alert",
        native_unit_of_measurement="mm",
        native_min_value=0.1,
        native_max_value=15,
        native_step=0.1,
        mode=NumberMode.BOX,
        clave_zona=Z_UMBRAL,
        defecto=DEFECTO_UMBRAL,
    ),
    DescripcionNumero(
        key="techo",
        name="Techo de seguridad",
        icon="mdi:water-off",
        native_unit_of_measurement="L",
        native_min_value=50,
        native_max_value=2000,
        native_step=10,
        mode=NumberMode.BOX,
        clave_zona=Z_TECHO,
        defecto=DEFECTO_TECHO,
    ),
    DescripcionNumero(
        key="factor",
        name="Coeficiente de ajuste",
        icon="mdi:tune-variant",
        native_min_value=0.1,
        native_max_value=2.0,
        native_step=0.05,
        mode=NumberMode.BOX,
        clave_zona=Z_FACTOR,
        defecto=DEFECTO_FACTOR_ZONA,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinador: RiegoCoordinator = hass.data[DOMAIN][entry.entry_id]
    entidades: list[NumberEntity] = [ProbabilidadLluvia(coordinador)]
    entidades += [
        NumeroZona(coordinador, zona[Z_ID], zona.get(Z_NOMBRE, zona[Z_ID]), d)
        for zona in coordinador.zonas
        for d in NUMEROS
    ]
    async_add_entities(entidades)


class ProbabilidadLluvia(EntidadSistema, NumberEntity):
    """Probabilidad desde la que una hora de la previsión es lluvia probable.

    El ciclo se aplaza si hay bastantes horas así (§7.23 en DECISIONES.md).
    """

    _attr_name = "Probabilidad de lluvia"
    _attr_icon = "mdi:weather-pouring"
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 10
    _attr_native_max_value = 100
    _attr_native_step = 5
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinador: RiegoCoordinator) -> None:
        super().__init__(coordinador, "probabilidad_lluvia")

    @property
    def native_value(self) -> float:
        return float(
            (self.coordinator.data or {}).get(
                "probabilidad_lluvia", DEFECTO_PROBABILIDAD_PREVISTA
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.set_probabilidad_lluvia(value)


class NumeroZona(EntidadZona, NumberEntity):
    entity_description: DescripcionNumero

    def __init__(
        self,
        coordinador: RiegoCoordinator,
        zid: str,
        nombre: str,
        descripcion: DescripcionNumero,
    ) -> None:
        super().__init__(coordinador, zid, nombre, descripcion.key)
        self.entity_description = descripcion

    @property
    def native_value(self) -> float:
        return float(
            self.coordinator.valor_zona(
                self._zid,
                self.entity_description.clave_zona,
                self.entity_description.defecto,
            )
        )

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.set_valor_zona(
            self._zid, self.entity_description.clave_zona, value
        )
