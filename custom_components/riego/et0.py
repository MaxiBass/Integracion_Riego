"""Evapotranspiración de referencia ET₀ — Penman-Monteith FAO-56 horaria.

Módulo puro (sin dependencias de Home Assistant) para que el cálculo sea
verificable de forma aislada.

Referencia: Allen, R.G. et al. (1998), *Crop evapotranspiration — Guidelines
for computing crop water requirements*, FAO Irrigation and Drainage Paper 56.
Se usa la formulación horaria (Ec. 53), con:

  · Corrección de la velocidad del viento a 2 m         (Ec. 47)
  · Radiación extraterrestre horaria calculada          (Ec. 28-33)
  · Radiación de cielo despejado Rso                    (Ec. 37)
  · Radiación neta de onda larga Rnl                    (Ec. 39)
  · Flujo de calor del suelo G: 0,1·Rn diurno / 0,5·Rn nocturno (Ec. 45-46)

Rn NO se trunca a cero: de noche el término radiativo es negativo y reduce
la ET₀, como indica FAO-56. La ET₀ resultante sí se trunca a ≥ 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

# Constante solar, MJ/m²/min
GSC = 0.0820
# Constante de Stefan-Boltzmann para paso horario, MJ/m²/h/K⁴
SIGMA_HORARIA = 2.042e-10
# Albedo del cultivo de referencia (hierba)
ALBEDO = 0.23
# Irradiancia por encima de la cual se considera que es de día (W/m²)
UMBRAL_DIURNO = 5.0


@dataclass(frozen=True)
class ResultadoET0:
    """Desglose del cálculo, útil para diagnóstico en los atributos."""

    et0: float
    ra: float
    rso: float
    rns: float
    rnl: float
    rn: float
    g: float
    u2: float
    f_cd: float
    termino_radiativo: float
    termino_aerodinamico: float


def correccion_viento(altura_m: float) -> float:
    """Factor de paso de la velocidad medida a `altura_m` a la de 2 m (Ec. 47)."""
    if altura_m <= 0:
        return 1.0
    if abs(altura_m - 2.0) < 1e-9:
        return 1.0
    return 4.87 / math.log(67.8 * altura_m - 5.42)


def radiacion_extraterrestre_horaria(
    momento: datetime, latitud: float, longitud: float, offset_utc_horas: float
) -> float:
    """Ra para el periodo de una hora centrado en `momento`, en MJ/m²/h (Ec. 28).

    `momento` debe ser consciente de zona horaria. `offset_utc_horas` es el
    desplazamiento del huso estándar local (p. ej. +1 para Europa/Madrid en
    horario de invierno, +2 en verano).
    """
    j = momento.timetuple().tm_yday

    # Distancia relativa inversa Tierra-Sol (Ec. 23) y declinación (Ec. 24)
    dr = 1.0 + 0.033 * math.cos(2.0 * math.pi * j / 365.0)
    decl = 0.409 * math.sin(2.0 * math.pi * j / 365.0 - 1.39)

    # Corrección estacional del tiempo solar (Ec. 32-33)
    b = 2.0 * math.pi * (j - 81) / 364.0
    sc = 0.1645 * math.sin(2.0 * b) - 0.1255 * math.cos(b) - 0.025 * math.sin(b)

    # Hora del reloj local en decimal, en el centro del periodo
    t = momento.hour + momento.minute / 60.0 + momento.second / 3600.0

    # Longitud del centro del huso horario, en grados al oeste de Greenwich
    lz = 15.0 * (-offset_utc_horas)
    # Longitud del emplazamiento, en grados al oeste de Greenwich
    lm = -longitud

    # Ángulo horario solar en el centro del periodo (Ec. 31)
    omega = math.pi / 12.0 * ((t + 0.06667 * (lz - lm) + sc) - 12.0)
    # Extremos del periodo de una hora (Ec. 29-30)
    omega1 = omega - math.pi / 24.0
    omega2 = omega + math.pi / 24.0

    phi = math.radians(latitud)
    ra = (
        (12.0 * 60.0 / math.pi)
        * GSC
        * dr
        * (
            (omega2 - omega1) * math.sin(phi) * math.sin(decl)
            + math.cos(phi) * math.cos(decl) * (math.sin(omega2) - math.sin(omega1))
        )
    )
    return max(ra, 0.0)


def presion_desde_altitud(altitud_m: float) -> float:
    """Presión atmosférica media en hPa a partir de la altitud (Ec. 7).

    FAO-56 la ofrece como sustituto aceptable cuando no hay barómetro. El
    valor que necesita la constante psicrométrica es la presión REAL del
    emplazamiento (absoluta), no la reducida a nivel del mar.
    """
    return 1013.0 * (((293.0 - 0.0065 * altitud_m) / 293.0) ** 5.26)


def presion_saturacion(t_c: float) -> float:
    """Presión de vapor a saturación en kPa (Ec. 11)."""
    return 0.6108 * math.exp((17.27 * t_c) / (t_c + 237.3))


def calcular(
    *,
    temperatura_c: float,
    humedad_pct: float,
    radiacion_wm2: float,
    viento_ms: float,
    presion_hpa: float,
    momento: datetime,
    latitud: float,
    longitud: float,
    altitud_m: float,
    offset_utc_horas: float,
    altura_anemometro_m: float = 7.0,
    viento_minimo_ms: float = 0.0,
) -> ResultadoET0:
    """ET₀ instantánea en mm/h para las condiciones dadas."""
    t = temperatura_c
    rh = min(max(humedad_pct, 1.0), 100.0)

    # Viento a 2 m, con suelo mínimo opcional recomendado por FAO-56
    u2 = max(viento_ms * correccion_viento(altura_anemometro_m), viento_minimo_ms)

    # Constante psicrométrica (Ec. 8); la presión llega en hPa = mbar
    presion_kpa = presion_hpa / 10.0
    gamma = 0.665e-3 * presion_kpa

    es = presion_saturacion(t)
    ea = es * rh / 100.0
    # Pendiente de la curva de presión de vapor (Ec. 13)
    delta = (4098.0 * es) / ((t + 237.3) ** 2)

    # Radiación neta de onda corta (Ec. 38). 1 W/m² durante 1 h = 0,0036 MJ/m²
    rs_mj = radiacion_wm2 * 0.0036
    rns = (1.0 - ALBEDO) * rs_mj

    # Radiación de cielo despejado (Ec. 37)
    ra = radiacion_extraterrestre_horaria(momento, latitud, longitud, offset_utc_horas)
    rso = (0.75 + 2e-5 * altitud_m) * ra

    # Factor de nubosidad. De noche no hay medida de Rs utilizable: FAO-56
    # sugiere arrastrar el valor del último periodo diurno; se usa 0,20, que
    # es el valor típico de cielo despejado nocturno y el que empleaba el
    # paquete YAML original.
    if radiacion_wm2 > UMBRAL_DIURNO and rso > 0.01:
        rs_rso = min(rs_mj / rso, 1.0)
        f_cd = max(1.35 * rs_rso - 0.35, 0.05)
    else:
        f_cd = 0.20

    f_hum = max(0.34 - 0.14 * math.sqrt(ea), 0.05)
    t_k = t + 273.16
    rnl = SIGMA_HORARIA * (t_k**4) * f_hum * f_cd

    rn = rns - rnl

    # Flujo de calor del suelo (Ec. 45-46)
    g = 0.1 * rn if radiacion_wm2 > UMBRAL_DIURNO else 0.5 * rn

    termino_radiativo = 0.408 * delta * (rn - g)
    termino_aerodinamico = gamma * (37.0 / (t + 273.0)) * u2 * (es - ea)
    denominador = delta + gamma * (1.0 + 0.34 * u2)

    if denominador <= 0:
        et0 = 0.0
    else:
        et0 = max((termino_radiativo + termino_aerodinamico) / denominador, 0.0)

    return ResultadoET0(
        et0=et0,
        ra=ra,
        rso=rso,
        rns=rns,
        rnl=rnl,
        rn=rn,
        g=g,
        u2=u2,
        f_cd=f_cd,
        termino_radiativo=termino_radiativo,
        termino_aerodinamico=termino_aerodinamico,
    )
