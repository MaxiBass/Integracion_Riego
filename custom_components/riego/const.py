"""Constantes de la integración Riego por Balance Hídrico."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "riego"
STORAGE_KEY: Final = "riego_estado"
STORAGE_VERSION: Final = 1

# Cada cuánto se recalcula la ET₀ instantánea y se integra al acumulado.
INTERVALO_ET0_SEGUNDOS: Final = 60

# Evento que dispara la integración en cada hito del ciclo. Permite al
# usuario engancharse con sus propias automatizaciones sin depender del
# servicio de notificación configurado.
EVENTO: Final = "riego_evento"

# ── Claves de configuración: sensores meteorológicos ──────────────────
CONF_SENSOR_TEMP: Final = "sensor_temperatura"
CONF_SENSOR_HUMEDAD: Final = "sensor_humedad"
CONF_SENSOR_RADIACION: Final = "sensor_radiacion"
CONF_SENSOR_VIENTO: Final = "sensor_viento"
CONF_SENSOR_PRESION: Final = "sensor_presion"
CONF_SENSOR_LLUVIA: Final = "sensor_lluvia_24h"
CONF_ALTURA_ANEMOMETRO: Final = "altura_anemometro"
CONF_VIENTO_MINIMO: Final = "viento_minimo"
CONF_FACTOR_RADIACION: Final = "factor_radiacion"

# ── Previsión de lluvia ───────────────────────────────────────────────
CONF_WEATHER: Final = "weather_entity"
CONF_FORECAST_TIPO: Final = "forecast_tipo"
CONF_FORECAST_HORAS: Final = "forecast_horas"
FORECAST_HORARIO: Final = "hourly"
FORECAST_DIARIO: Final = "daily"

# ── Parámetros de lluvia y protecciones ───────────────────────────────
CONF_LLUVIA_MINIMA: Final = "lluvia_minima"
CONF_LLUVIA_CAP: Final = "lluvia_cap"
CONF_LLUVIA_PREVISTA: Final = "lluvia_prevista_umbral"
CONF_TEMP_HELADA: Final = "temp_helada"
CONF_DEFICIT_MAXIMO: Final = "deficit_maximo"

# ── Planificación del ciclo ───────────────────────────────────────────
CONF_MODO_INICIO: Final = "modo_inicio"
MODO_FIN_AMANECER: Final = "fin_amanecer"
MODO_OFFSET_AMANECER: Final = "offset_amanecer"
MODO_HORA_FIJA: Final = "hora_fija"

CONF_OFFSET_AMANECER: Final = "offset_amanecer_min"
CONF_HORA_FIJA: Final = "hora_fija_valor"
CONF_DESFASE_ZONAS: Final = "desfase_zonas"
CONF_HORA_MINIMA: Final = "hora_minima"
CONF_MARGEN_DURACION: Final = "margen_duracion"

# ── Operación ─────────────────────────────────────────────────────────
CONF_SIMULACION: Final = "simulacion"
CONF_NOTIFY: Final = "notify_entity"
CONF_ZONAS: Final = "zonas"

# ── Claves de cada zona ───────────────────────────────────────────────
Z_ID: Final = "id"
Z_NOMBRE: Final = "nombre"
Z_M2: Final = "m2"
Z_UMBRAL: Final = "umbral"
Z_TECHO: Final = "techo"
Z_KC: Final = "kc"
Z_TOPIC: Final = "topic"
Z_SENSOR_ESTADO: Final = "sensor_estado"
Z_SENSOR_CAUDAL: Final = "sensor_caudal"
Z_SENSOR_VOLUMEN: Final = "sensor_volumen_real"
Z_SENSOR_DURACION: Final = "sensor_duracion_real"
Z_CAUDAL_DEFECTO: Final = "caudal_defecto"
Z_FACTOR: Final = "factor"

# ── Valores por defecto ───────────────────────────────────────────────
# viento_minimo: FAO-56 recomienda acotar u2 a 0,5 m/s para que el término
# aerodinámico no se desplome con viento muy flojo. Por defecto va a 0,0
# para reproducir exactamente el paquete YAML que esta integración
# sustituye; subirlo a 0,5 aumenta la ET₀ en emplazamientos resguardados.
DEFECTO_ALTURA_ANEMOMETRO: Final = 7.0
DEFECTO_VIENTO_MINIMO: Final = 0.0
# Calibración del piranómetro. La estación de este emplazamiento supera el
# máximo teórico de cielo despejado varias horas al día, síntoma habitual de
# los sensores que derivan W/m² de un lux-metro con factor fijo. Se deja a
# 1,0 para no alterar nada sin decisión explícita.
DEFECTO_FACTOR_RADIACION: Final = 1.0
DEFECTO_LLUVIA_MINIMA: Final = 2.0
DEFECTO_LLUVIA_CAP: Final = 20.0
DEFECTO_LLUVIA_PREVISTA: Final = 3.0
DEFECTO_TEMP_HELADA: Final = 1.0
DEFECTO_DEFICIT_MAXIMO: Final = 50.0
DEFECTO_FORECAST_HORAS: Final = 24
DEFECTO_OFFSET_AMANECER: Final = -35
DEFECTO_HORA_FIJA: Final = "03:00:00"
DEFECTO_DESFASE_ZONAS: Final = 60
DEFECTO_HORA_MINIMA: Final = "00:00:00"
DEFECTO_MARGEN_DURACION: Final = 15
DEFECTO_CAUDAL: Final = 280.0

# Kc mensual por defecto: cubierta vegetal genérica de porte medio.
DEFECTO_KC: Final = [0.40, 0.40, 0.45, 0.50, 0.55, 0.60,
                     0.60, 0.60, 0.55, 0.50, 0.45, 0.40]

DEFECTO_M2: Final = 50.0
DEFECTO_UMBRAL: Final = 0.5
DEFECTO_TECHO: Final = 800.0
# Coeficiente de ajuste por zona. Multiplica a ETc antes de convertir a
# litros. Sirve para riego localizado (solo se moja una fracción del suelo)
# y para riego deficitario controlado. 1,0 = dosis FAO-56 íntegra.
DEFECTO_FACTOR_ZONA: Final = 1.0

# Estados de la electroválvula que impiden regar. El déficit se conserva.
ESTADOS_FALLO: Final = (
    "water_leakage",
    "water_shortage",
    "water_shortage & water_leakage",
)

# Suavizado exponencial del caudal aprendido por zona.
EMA_ALFA: Final = 0.3
CAUDAL_MIN_VALIDO: Final = 50.0
CAUDAL_MAX_VALIDO: Final = 2000.0
VOLUMEN_MIN_MUESTRA: Final = 20.0

# Estados publicados por sensor.<zona>_estado
ESTADO_DESHABILITADA: Final = "deshabilitada"
ESTADO_ACUMULANDO: Final = "acumulando"
ESTADO_LISTA: Final = "lista"
ESTADO_REGANDO: Final = "regando"
ESTADO_BLOQUEADA: Final = "bloqueada"
