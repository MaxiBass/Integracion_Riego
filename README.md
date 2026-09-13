# Integracion_Riego

Integración custom de Home Assistant: **riego por balance hídrico FAO-56**.
Calcula la evapotranspiración de referencia (Penman-Monteith horaria) a
partir de una estación meteorológica local, acumula el déficit hídrico de
cada zona y dosifica por volumen sobre electroválvulas Zigbee con riego
cuantitativo (probado con SONOFF SWV vía Zigbee2MQTT).

Historial de decisiones, hallazgos de la revisión y plan de migración:
[`docs/DECISIONES.md`](docs/DECISIONES.md).

## Qué hace

- **ET₀ horaria FAO-56** con radiación extraterrestre calculada, corrección
  de viento a 2 m, onda larga real y flujo de calor del suelo.
- **Déficit por zona**: `déficit += ET₀ × Kc × factor − lluvia efectiva`.
- **Dosis volumétrica**: `litros = déficit × m²`, acotada por el techo de
  seguridad de la zona.
- **Hora de inicio calculada hacia atrás desde el amanecer**, estimando la
  duración con el caudal que aprende de cada zona.
- **Protecciones**: helada, lluvia prevista (aplazamiento de un día) y
  válvula en fallo — en los tres casos el déficit se conserva.
- **Modo simulación**: calcula y avisa, pero no envía nada a las válvulas.
- **Estadísticas de temporada** por zona, con `state_class` para el
  histórico a largo plazo.
- **Panel automático** por estrategia de Lovelace, con tarjetas nativas.

## Instalación vía HACS

1. HACS → menú ⋮ → **Repositorios personalizados**.
2. URL: `https://github.com/MaxiBass/Integracion_Riego`, categoría
   **Integración**.
3. Instalar **Riego por Balance Hídrico** desde HACS.
4. Reiniciar Home Assistant.
5. Ajustes → Dispositivos y servicios → Añadir integración → **Riego por
   Balance Hídrico**.

El alta pide, en cuatro pasos: sensores meteorológicos, fuente de previsión
y protecciones, planificación del ciclo y la primera zona. Todo es
reconfigurable después desde **Configurar**, incluidas las zonas.

## Instalación manual (sin HACS)

Copia `custom_components/riego` a `/config/custom_components/riego` y
reinicia.

## Panel

La integración sirve la estrategia de panel automáticamente. Para usarla:

1. Ajustes → Paneles → **Añadir panel** → *Nuevo panel desde cero*.
2. Abrir el panel → lápiz → menú ⋮ → **Editor de control en bruto**.
3. Sustituir todo el contenido por:

```yaml
strategy:
  type: custom:riego
```

El panel se reconstruye solo cuando añades o quitas zonas. Si no aparece,
recarga con Ctrl+F5: el módulo se sirve en `/riego_static/riego-strategy.js`.

## Servicios

| Servicio | Para qué |
|---|---|
| `riego.ejecutar_ciclo` | Lanza el ciclo ahora. Devuelve el detalle de lo hecho. |
| `riego.regar_zona` | Dosis puntual a una zona, al margen del balance. |
| `riego.ajustar_deficit` | Fija o corrige el déficit de una zona. |
| `riego.saltar_dia` | El próximo ciclo solo acumula, sin regar. |
| `riego.reiniciar_temporada` | Pone a cero los litros de temporada. |

Además, cada hito del ciclo dispara el evento `riego_evento`, por si
prefieres construir tus propios avisos en lugar de usar la entidad de
notificación.

## Requisitos

- Home Assistant 2024.6 o posterior.
- La integración **MQTT** configurada.
- Una estación meteorológica local con, como mínimo, temperatura, humedad y
  radiación solar. Con viento y presión el cálculo es bastante mejor.
