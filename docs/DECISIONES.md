# Decisiones — Riego por Balance Hídrico

Historial de por qué esta integración es como es. Escrito tras revisar el
sistema de riego que ya funcionaba en el HA de casa (paquete YAML
`packages/riego/` + una automatización maestra), del que esta integración es
el sustituto.

Fecha de la revisión: **13 de septiembre de 2026**. HA 2026.9.2.

---

## 1. Punto de partida

Tres zonas regadas por goteo con electroválvulas **SONOFF SWV** (Zigbee,
vía Zigbee2MQTT), dosificadas por volumen con
`cyclic_quantitative_irrigation`:

| Zona | Superficie | Kc septiembre | Techo | Caudal medido |
|---|---|---|---|---|
| Frutales | 140 m² | 0,71 | 500 L | 289 L/h |
| Aptenia | 80 m² | 0,55 | 350 L | 286 L/h |
| Cipreses | 45 m² | 0,44 | 250 L | 278 L/h |

El sistema YAML calculaba ET₀ horaria por Penman-Monteith, la integraba con
`integration` + `utility_meter`, acumulaba déficit por zona y regaba al
amanecer −35 min. **Funcionaba**: la reconstrucción de agosto cuadra litro a
litro con lo que realmente se regó.

---

## 2. Hallazgos de la revisión

### 2.1 Error de unidades en la constante psicrométrica (el importante)

FAO-56 Ec. 8 es `γ = 0,665·10⁻³ · P` **con P en kPa**. La plantilla pasaba
`sensor.estacion_meteorologica_absolute_pressure`, que está en **hPa**, así
que `γ` salía 10× de más.

El efecto no es un factor limpio, porque `γ` aparece en dos sitios con signos
opuestos: infla el término aerodinámico ×10 y el denominador ×3,3. Medido
sobre un día real completo (12/09/2026, con las medias horarias de la
estación):

| | mm/día |
|---|---|
| Fórmula del YAML (réplica) | 3,15 |
| **Registrado por HA ese día** | **3,10** ← la réplica es fiel |
| Fórmula corregida | **4,45** |

**La ET₀ estaba subestimada un ~40 %.** El valor corregido cae justo en la
climatología de Alicante para septiembre (3,9–4,5 mm/día), que es la mejor
confirmación de que el arreglo es correcto.

Consecuencia práctica: el jardín llevaba tiempo recibiendo en torno al 70 %
de la dosis FAO-56. Ver §4.3 sobre qué hacer con eso.

### 2.2 Tabla `Rso` incorrecta

La radiación de cielo despejado estaba codificada como una tabla mensual en
W/m² con valores aproximadamente la mitad del máximo horario real
(septiembre: 411 en la tabla frente a 814 W/m² a mediodía solar). Eso satura
`Rs/Rso` a 1,0 buena parte del día y sobrestima la pérdida de onda larga.

Cuantificado sobre una hora típica de agosto el efecto es **~2 % de ET₀**, no
es la causa de nada. Se sustituye igualmente por Ra calculada
astronómicamente (FAO-56 Ec. 28-33) porque es gratis y porque elimina una
tabla atada a una latitud concreta.

### 2.3 El piranómetro lee alto

El 12/09 la radiación medida superó el máximo teórico de cielo despejado
durante **8 horas**. Típico de los sensores que derivan W/m² de un lux-metro
con factor fijo. Se añade `factor_radiacion` (por defecto 1,0, sin cambiar
nada) para poder calibrarlo cuando haya una referencia con la que comparar.

### 2.4 El techo de seguridad estaba racionando

Reconstrucción de agosto para Frutales:

| Día | Volumen debido | Regado | Recorte |
|---|---|---|---|
| 18/08 | 510 L | 500 | −10 |
| 20/08 | — | 0 (aplazado) | pendiente |
| 21/08 | 957 L | 500 | −457 |
| 22/08 | 843 L | 500 | −343 |
| 23/08 | 702 L | 500 | −202 |
| 24/08 | 472 L | 472 ✓ | recuperado |

Cuatro días seguidos recortando en plena ola de calor, y eso **con la ET₀
subestimada**. Un techo de seguridad debe estar por encima del máximo
legítimo; si recorta de forma habitual es racionamiento, no protección.

### 2.5 Una zona bloqueada pasa desapercibida durante días

Cipreses no regó el 11 ni el 12 de septiembre: la válvula reportaba
`water_leakage` desde el día 9. La protección hizo lo correcto (saltar y
conservar el déficit), pero solo avisaba una vez por ciclo y no había forma
de ver «llevas 3 días sin regar esta zona». De ahí
`binary_sensor.<zona>_bloqueada` y el estado explícito por zona.

### 2.6 Solapamiento entre zonas: no es un problema

Se midió el caudal de Frutales sola (200–300 L/h) y con las tres abiertas
(200–300 L/h). **No hay caída de presión por solapamiento.** Se descartó
rediseñar el sistema a riego estrictamente secuencial: no aportaría nada
hidráulico.

### 2.7 Otros, menores

- Los sensores `irrigation_start_time` de las válvulas no comparten base de
  tiempo: Frutales reporta en UTC y las otras dos en hora local. No se usan.
- La vigilancia de caudal alto se salvaba por 14 s: el pico de apertura
  (1.300–1.400 L/h) dura ~26 s y el disparador exige 40 s.
- `daily_irrigation_volume` no tenía `state_class`, así que no había
  estadísticas a largo plazo de litros.

---

## 3. Por qué integración y no add-on

Un add-on es un contenedor Docker aparte: se justifica cuando hace falta un
proceso externo, dependencias pesadas o hablar con una API de terceros. Aquí
todo vive dentro de Home Assistant — estados, MQTT, servicios, almacenamiento
— así que un add-on solo añadiría un canal extra, latencia y un punto de
fallo. Integración.

---

## 4. Decisiones de diseño

### 4.1 La hora de inicio se calcula hacia atrás desde el amanecer

El arranque del sistema anterior (amanecer −35 min) era correcto: la franja
04:00–08:00 es la óptima para goteo. El problema era que **el final derivaba
con la dosis**: en agosto, con 500 L a 290 L/h, Frutales cerraba hacia las
08:25.

Modo por defecto `fin_amanecer`: se estima la duración de cada zona
(`litros ÷ caudal aprendido`), se calcula `max(i·desfase + duración_i)` y se
arranca a esa distancia del amanecer. El suelo queda recargado justo cuando
la planta empieza a transpirar. Se mantienen `offset_amanecer` y `hora_fija`
como alternativas configurables.

### 4.2 Dispara y olvida, con desfase de 1 minuto

Se descartó esperar confirmación de fin de riego. `cyclic_quantitative_irrigation`
lo ejecuta la válvula de forma **autónoma**: si HA se reinicia o Zigbee se cae
a mitad de riego, la válvula termina su dosis y cierra sola. Depender de que
HA espere sería *menos* robusto, no más.

El desfase entre zonas es configurable (por defecto 60 s) y no pretende
secuenciar: solo escalona la apertura.

### 4.3 Coeficiente de ajuste por zona — la decisión pendiente

Arreglar §2.1 hace que la ET₀ suba ~40 %, y con ella los litros. Frutales en
septiembre pasaría de ~308 a ~435 L/día.

**No se ha tomado esa decisión por el usuario.** La integración expone
`number.zona_<x>_coeficiente_de_ajuste`, que multiplica a ETc antes de
convertir a litros, con dos usos legítimos:

- **Riego localizado.** Con goteo solo se moja una fracción del suelo; aplicar
  ETc sobre la superficie completa de la parcela sobrestima si la cubierta
  vegetal no es total. FAO-56 contempla un coeficiente de localización.
- **Riego deficitario controlado**, que es de hecho lo que el sistema llevaba
  haciendo sin saberlo.

Valor por defecto **1,0** (dosis FAO íntegra). Poner **0,70** reproduce
aproximadamente el riego actual. La decisión se toma tras comparar en modo
simulación, no antes.

### 4.4 El riego manual NO descuenta del déficit

Decisión explícita del usuario. Consecuencia asumida: si se riega a mano, el
ciclo siguiente vuelve a regar encima. El servicio `riego.ajustar_deficit`
permite corregirlo a mano cuando interese.

### 4.5 Fuente de previsión intercambiable

`weather_entity` + `forecast_tipo` (horaria/diaria) + horizonte, todo en el
flujo de opciones. No hay ninguna referencia a AEMET en el código. Si la
consulta falla, se registra un aviso y el ciclo continúa: la previsión nunca
debe impedir un riego.

### 4.6 Estado en `.storage`, no en 26 `input_number`

El déficit, los litros de temporada, el caudal aprendido y la bandera de
aplazamiento viven en el almacén de la integración. La configuración solo
**siembra** los valores iniciales; a partir de ahí la fuente de verdad son
las entidades `number`/`switch`, para que ajustar un parámetro desde el panel
no obligue a recargar la entrada de configuración.

### 4.7 Panel por estrategia, no autogenerado

De las cuatro vías estudiadas para que la integración cree el panel:

1. **Estrategia de Lovelace** ← elegida. La integración sirve un módulo JS y
   el panel se construye solo a partir de las entidades.
2. Panel propio en la barra lateral: mucho más trabajo.
3. Escribir directamente en el almacenamiento de Lovelace: **descartada**, no
   es API pública y se rompe entre versiones.
4. Generar YAML para pegar a mano: queda como respaldo.

La creación del panel **no** es automática: hay que crearlo una vez y elegir
la estrategia (tres clics, ver README). Se prefirió eso a tocar APIs
privadas. La estrategia usa solo tarjetas nativas, para no depender de
mushroom, apexcharts ni mini-graph-card.

### 4.8 Modo simulación por defecto

La integración arranca con `switch.balance_hidrico_modo_simulacion` en ON:
calcula todo el ciclo, avisa por Telegram de lo que habría regado y **no
envía nada a las válvulas**. Es la forma prevista de rodarla en paralelo con
el sistema antiguo antes de cambiar.

---

## 5. Cómo pausar el sistema actual

El único elemento que manda agua a las válvulas es la automatización
**«Riego — Ciclo diario al amanecer»** (`automation.riego_ciclo_diario_al_amanecer`).
El resto del paquete YAML (plantillas, helpers, sensores) solo calcula: es
inerte y puede convivir sin riesgo.

Para pausar:

```yaml
action: automation.turn_off
target:
  entity_id: automation.riego_ciclo_diario_al_amanecer
```

Para volver atrás, `automation.turn_on` sobre la misma entidad. El déficit
del sistema antiguo sigue en `input_number.deficit_*` intacto.

Las dos automatizaciones de notificación (`Notificaciones Riego Telegram 1` y
`Vigilancia de caudal anómalo`) conviene **dejarlas encendidas** durante la
convivencia: vigilan el hardware, no mandan agua, y sirven de red de
seguridad independiente.

Cuidado con `number.riego_*_litros`: son entidades MQTT del paquete antiguo
que publican en el mismo topic. No se borran, pero no hay que tocarlas.

### Orden recomendado

1. Instalar la integración con **modo simulación ON** y la automatización
   antigua **encendida**. Ambos sistemas calculan; solo riega el viejo.
2. Sembrar el déficit inicial de cada zona con `riego.ajustar_deficit`, con
   los valores de `input_number.deficit_*`.
3. Dejar correr 3–5 días. Comparar la ET₀ de los dos y los litros que cada
   sistema propone. Aquí es donde se decide el coeficiente de §4.3.
4. Cuando cuadre: apagar la automatización antigua y apagar el modo
   simulación, **en ese orden**.
5. Tras una temporada estable, retirar `packages/riego/` y el panel viejo.

---

## 6. Limitaciones conocidas

- La duración estimada usa el caudal aprendido por EMA. Con la instalación
  recién puesta usa `caudal_defecto` hasta que hay una muestra real.
- Con `fin_amanecer`, la planificación ocurre 8 h antes del amanecer usando
  el déficit *proyectado*. Si llueve entre la planificación y el ciclo, la
  hora de arranque queda algo desplazada. El riego en sí sí usa los valores
  del momento.
- El aplazamiento por lluvia es de un día como máximo, igual que el sistema
  anterior: si al día siguiente sigue dando lluvia, riega igual.
- La API de estrategias de Lovelace no está congelada; si una actualización
  de HA la rompe, el panel se puede rehacer a mano con tarjetas normales.
- No hay tests automatizados. `et0.py` no tiene dependencias de HA
  precisamente para poder probarlo aislado; escribirlos está pendiente.
