"""Sensores de Riego por Balance Hídrico."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, Z_ID, Z_NOMBRE
from .coordinator import RiegoCoordinator
from .entity import EntidadSistema, EntidadZona


@dataclass(frozen=True, kw_only=True)
class DescripcionSensor(SensorEntityDescription):
    """Descripción con el extractor del valor."""

    valor: Callable[[dict[str, Any]], Any]
    atributos: Callable[[dict[str, Any]], dict[str, Any]] | None = None


SENSORES_SISTEMA: tuple[DescripcionSensor, ...] = (
    DescripcionSensor(
        key="et0_instantanea",
        name="ET₀ instantánea",
        icon="mdi:water-percent",
        native_unit_of_measurement="mm/h",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda d: d.get("et0_instantanea"),
        atributos=lambda d: d.get("et0_detalle", {}),
    ),
    DescripcionSensor(
        key="et0_acumulada",
        name="ET₀ acumulada del periodo",
        icon="mdi:water-minus",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda d: d.get("et0_acumulada"),
    ),
    DescripcionSensor(
        key="et0_periodo_anterior",
        name="ET₀ del periodo anterior",
        icon="mdi:water-check",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda d: d.get("et0_periodo_anterior"),
    ),
    DescripcionSensor(
        key="lluvia_efectiva",
        name="Lluvia efectiva",
        icon="mdi:weather-rainy",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda d: d.get("lluvia_efectiva"),
    ),
    DescripcionSensor(
        key="proximo_ciclo",
        name="Próximo ciclo",
        icon="mdi:clock-start",
        device_class=SensorDeviceClass.TIMESTAMP,
        valor=lambda d: d.get("proximo_ciclo"),
        atributos=lambda d: {"amanecer": d.get("amanecer")},
    ),
    DescripcionSensor(
        key="ultimo_ciclo",
        name="Último ciclo",
        icon="mdi:clock-check",
        device_class=SensorDeviceClass.TIMESTAMP,
        valor=lambda d: dt_util.parse_datetime(d["ultimo_ciclo"])
        if d.get("ultimo_ciclo")
        else None,
    ),
)

SENSORES_ZONA: tuple[DescripcionSensor, ...] = (
    DescripcionSensor(
        key="deficit",
        name="Déficit acumulado",
        icon="mdi:water-minus",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda z: z.get("deficit"),
        atributos=lambda z: {
            "umbral_mm": z.get("umbral"),
            "kc_mes": z.get("kc"),
            "factor_zona": z.get("factor"),
            "volumen_equivalente_l": round(z.get("deficit", 0) * z.get("m2", 0)),
        },
    ),
    DescripcionSensor(
        key="falta_para_regar",
        name="Falta para regar",
        icon="mdi:water-alert",
        native_unit_of_measurement="mm",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda z: z.get("falta"),
    ),
    DescripcionSensor(
        key="volumen_objetivo",
        name="Volumen objetivo",
        icon="mdi:water",
        native_unit_of_measurement="L",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda z: z.get("volumen"),
        atributos=lambda z: {
            "duracion_estimada_min": z.get("duracion_min"),
            "caudal_aprendido_l_h": z.get("caudal"),
            "techo_l": z.get("techo"),
        },
    ),
    DescripcionSensor(
        key="kc",
        name="Kc del mes",
        icon="mdi:leaf",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda z: z.get("kc"),
    ),
    DescripcionSensor(
        key="litros_hoy",
        name="Litros del último ciclo",
        icon="mdi:water-check",
        native_unit_of_measurement="L",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda z: z.get("litros_hoy"),
    ),
    DescripcionSensor(
        key="litros_temporada",
        name="Litros de la temporada",
        icon="mdi:chart-line",
        native_unit_of_measurement="L",
        device_class=SensorDeviceClass.WATER,
        state_class=SensorStateClass.TOTAL_INCREASING,
        valor=lambda z: z.get("litros_temporada"),
    ),
    DescripcionSensor(
        key="caudal_aprendido",
        name="Caudal aprendido",
        icon="mdi:speedometer",
        native_unit_of_measurement="L/h",
        state_class=SensorStateClass.MEASUREMENT,
        valor=lambda z: z.get("caudal"),
    ),
    DescripcionSensor(
        key="estado",
        name="Estado",
        icon="mdi:state-machine",
        device_class=SensorDeviceClass.ENUM,
        options=["deshabilitada", "acumulando", "lista", "regando", "bloqueada"],
        valor=lambda z: z.get("estado"),
    ),
    DescripcionSensor(
        key="ultimo_riego",
        name="Último riego",
        icon="mdi:calendar-clock",
        device_class=SensorDeviceClass.TIMESTAMP,
        valor=lambda z: dt_util.parse_datetime(z["ultimo_riego"])
        if z.get("ultimo_riego")
        else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinador: RiegoCoordinator = hass.data[DOMAIN][entry.entry_id]
    entidades: list[SensorEntity] = [
        SensorSistema(coordinador, d) for d in SENSORES_SISTEMA
    ]
    for zona in coordinador.zonas:
        for d in SENSORES_ZONA:
            entidades.append(
                SensorZona(coordinador, zona[Z_ID], zona.get(Z_NOMBRE, zona[Z_ID]), d)
            )
    async_add_entities(entidades)


class SensorSistema(EntidadSistema, SensorEntity):
    entity_description: DescripcionSensor

    def __init__(self, coordinador: RiegoCoordinator, descripcion: DescripcionSensor) -> None:
        super().__init__(coordinador, descripcion.key)
        self.entity_description = descripcion

    @property
    def native_value(self) -> Any:
        return self.entity_description.valor(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.atributos is None:
            return None
        return self.entity_description.atributos(self.coordinator.data or {})


class SensorZona(EntidadZona, SensorEntity):
    entity_description: DescripcionSensor

    def __init__(
        self,
        coordinador: RiegoCoordinator,
        zid: str,
        nombre: str,
        descripcion: DescripcionSensor,
    ) -> None:
        super().__init__(coordinador, zid, nombre, descripcion.key)
        self.entity_description = descripcion

    @property
    def native_value(self) -> Any:
        return self.entity_description.valor(self._zona)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.atributos is None:
            return None
        return self.entity_description.atributos(self._zona)
