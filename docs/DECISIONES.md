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
- La cobertura de `tests/test_riego.py` es de comportamiento, no exhaustiva:
  cubre ET₀, los dos flujos de configuración y las ramas del ciclo, pero no
  las entidades ni la estrategia de panel.


---

## 7. Incidencias posteriores

### 7.1 `400: Bad Request` al abrir el flujo de configuración (v0.1.0)

Primer intento de instalación: la integración aparecía en la lista, pero al
pulsarla el frontend devolvía *«No se pudo cargar el flujo de configuración:
400: Bad Request»*.

Se descartó por razonamiento que fuera un fallo de importación (eso habría
dado 404, no 400) y que fueran las dependencias (`mqtt` estaba cargado con
500 entidades). El log en memoria de HA no tenía ninguna entrada de `riego`,
y el fichero de log en disco está desactivado en esta instalación, así que
no había traza que leer.

Se reprodujo instalando Home Assistant 2026.9.2 en un entorno aislado y
construyendo el formulario igual que lo hace el frontend:

```
probatio.error.MultipleInvalid: expected str at 'unit_of_measurement'
```

`NumberSelectorConfig` rechaza `unit_of_measurement=None`. El ayudante
`_numero()` lo pasaba siempre, así que cualquier campo numérico **sin
unidad** —`factor_radiacion` y el coeficiente de ajuste por zona— reventaba
al construir el primer paso. Arreglado en v0.1.1 incluyendo la clave solo
cuando hay unidad.

De aquí salieron dos cosas más:

- `tests/test_riego.py`, que recorre los dos flujos completos y serializa
  cada esquema con `probatio.to_field_list`, que es exactamente lo que HA
  manda al navegador. Este fallo se habría detectado antes de instalar.
- El coordinador ahora pasa `config_entry` explícitamente a
  `DataUpdateCoordinator`, como recomienda HA.

Nota para futuras versiones: HA 2026.9 ya no usa `voluptuous_serialize` para
los esquemas de los flujos, usa `to_field_list` de **probatio**, que sustituye
a `voluptuous`. Al probar hay que importar `homeassistant` **antes** que nada
que importe `voluptuous`, o las referencias no se resuelven.

---

## 8. La estación meteorológica (Ecowitt vía MQTT)

Inventario de lo que publica `sensor.estacion_meteorologica_raw_data` y qué
usa la integración:

| Campo Ecowitt | Entidad | Uso en ET₀ |
|---|---|---|
| `tempf` | Outdoor Temperature (°C) | **Temperatura** |
| `humidity` | Humidity (%) | **Humedad relativa** |
| `solarradiation` | Solar Radiation (W/m²) | **Radiación** |
| `baromabsin` | Absolute Pressure (hPa) | **Presión** |
| `baromrelin` | Relative Pressure (hPa) | no usar |
| `windspeedmph` | Wind Speed (km/h) | **Viento** |
| `last24hrainin` | 24h Rain (mm) | **Lluvia efectiva** |
| `vpd` | Vapour Pressure Deficit (kPa) | no usado; la integración calcula es−ea |
| `uv`, `winddir`, `dewpoint`, lluvias varias, interiores | — | no usados |

### 8.1 Humedad: relativa

`humidity` es humedad **relativa** en % (entero 0-100), que es la que pide
FAO-56. La absoluta iría en g/m³ y la estación no la publica.

### 8.2 Presión: la absoluta

FAO-56 Ec. 8 necesita la presión **real del emplazamiento**, no la reducida
a nivel del mar. En Ecowitt eso es `baromabsin`.

En esta instalación concreta ambas marcan lo mismo (1003,4 hPa) porque el
offset de presión relativa nunca se configuró en la consola. Aunque
divergieran, a 120 m de altitud la diferencia en ET₀ es del **0,28 %**
(hay una prueba que lo comprueba). La elección importa poco aquí, pero la
correcta es la absoluta.

Desde v0.2.0 el sensor de presión es **opcional**: sin él se estima a partir
de la altitud configurada en Home Assistant (FAO-56 Ec. 7), que a 120 m da
998,9 hPa frente a los 1003,4 medidos — dentro del 1 % en ET₀.

### 8.3 Iluminancia como alternativa a la radiación

Desde v0.2.0 se puede alimentar la ET₀ con un sensor de **lux** en lugar de
uno de W/m², con factor de conversión configurable (126,7 por defecto, que
es el que usan Ecowitt y Fine Offset).

Aviso importante para esta instalación: `sensor.estacion_meteorologica_solar_lux`
**no es una medida independiente**, se calcula como
`solarradiation × 126.7`. Dividirlo otra vez por 126,7 devuelve exactamente
el valor de partida, así que aquí da igual cuál se elija. La opción existe
para estaciones que solo publican lux.

Esto también explica por qué el piranómetro supera el máximo teórico de
cielo despejado (§2.3): el hardware mide luz y deriva W/m² con un factor
fijo, cuando la eficacia luminosa real de la radiación solar varía con la
altura del sol y la nubosidad.

### 8.4 Bug de precedencia en la conversión de viento

En `packages/meteorologia/estacion.yaml`:

```jinja
{{ mph | float * 1.60934 | round(1) }}
```

El filtro `round(1)` se aplica a la constante, no al producto, así que
multiplica por **1,6** en vez de 1,60934 y el `round` nunca actúa. El viento
sale un **0,58 % bajo**. Afecta a Wind Speed, Wind Gust y Max Daily Gust. El
paréntesis correcto es `{{ (mph | float * 1.60934) | round(1) }}`.

Impacto en ET₀: despreciable (el término aerodinámico es una fracción
pequeña del total).

**Corregido el 13/09/2026** a petición del usuario, directamente sobre el HA
en producción. Como el fichero está en un subdirectorio, el backup
automático de la herramienta **no lo cubre** (solo respalda los YAML de
primer nivel), así que antes de escribir se reconstruyó el original en local
y se validó comparando el conjunto de `unique_id` del fichero contra las
entidades vivas de HA: coincidencia exacta, sin sobras ni faltas. El diff
aplicado fue de exactamente tres líneas.

Verificación posterior a `template.reload`: 35 entidades antes y después,
ninguna en `unavailable` ni `unknown`, y las tres de viento pasando a
2,91 mph → 4,7 km/h (antes 4,656), 5,82 → 9,4 y 13,65 → 22,0. El resto de
sensores del paquete, sin cambios.

Efecto secundario buscado: ahora el `round(1)` sí se aplica, así que las tres
entidades publican un decimal en lugar de la ristra de decimales que salía
del producto sin redondear.


### 7.2 `Value 126.7 is too large` y el factor del piranómetro desaparecido (v0.2.0)

Al editar `esquema_meteo` para añadir la entrada por lux se usó una
sustitución de texto sobre `"    CONF_FACTOR_RADIACION,\n"` con la intención
de tocar solo la lista de imports. Esa cadena también es un subconjunto de
la línea indentada a 16 espacios dentro de la función, así que el campo
quedó como:

```python
vol.Required(
    CONF_FACTOR_LUX,
    CONF_FACTOR_RADIACION,      # <- pasa a ser el argumento `msg`
    default=...,
): _numero(0.5, 1.5, 0.01),
```

Es Python válido y voluptuous válido: el segundo posicional de un `Marker`
es `msg`. Resultado: el campo «luxes por W/m²» heredó los límites del factor
del piranómetro (0,5–1,5) y rechazaba su propio valor por defecto de 126,7,
mientras que `factor_radiacion` desaparecía del formulario.

La prueba existente no lo detectó porque solo comprobaba que el esquema
serializara a JSON. Ahora se verifica además **el conjunto exacto de campos
del paso** y que **el valor por defecto de cada campo numérico caiga dentro
de su propio rango**, que es lo que habría cazado este fallo y el de §7.1 de
una sola vez.

Lección aplicable a este repo: editar Python con sustituciones de texto sin
anclar la indentación completa es frágil. Si hay que hacerlo, incluir en el
patrón la indentación real de la línea.

### 7.3 El alta no llegaba a crearse (v0.2.1)

El usuario rellenó los cuatro pasos y las tres zonas, pero no aparecía
ninguna integración. Comprobado en su HA: **no existía ninguna entrada de
configuración de `riego`**, y no había ni un solo error de la integración en
el log. Es decir, el flujo no falló: nunca llegó a `async_create_entry`.

La primera hipótesis —que el usuario hubiera cerrado el diálogo sin pulsar
«Enviar»— **era falsa**. Él confirmó que sí pulsaba Enviar y que no ocurría
nada. La causa real:

`vol.Required("añadir_otra", default=False)` con un `bool` crudo se
serializa como `{"type": "boolean", "required": true}`. Cuando la casilla
está **marcada**, `ha-form` la da por rellena y el envío funciona — por eso
sí se podían encadenar zonas. Cuando se **desmarca**, el valor `false` se
interpreta como campo obligatorio sin rellenar y el envío queda **bloqueado
sin mostrar ningún error**: se pulsa Enviar y no pasa nada.

Es decir, el único camino que creaba la integración era justo el único que
el formulario impedía recorrer.

Sustituido por un menú de dos opciones explícitas —«➕ Añadir otra zona» y
«✅ Terminar y crear la integración»—, que no tiene campos y por tanto no
puede quedar bloqueado.

**La misma trampa estaba en un segundo sitio**: `simulacion`, en el paso de
planificación del ciclo, también era un booleano obligatorio. Arrancando en
`true` no daba problema, pero habría bloqueado el envío justo al intentar
desmarcarlo en Opciones → Ciclo, que es precisamente el gesto de pasar de
simulación a riego real. Cambiado a `vol.Optional`, y añadida una prueba que
prohíbe booleanos obligatorios en cualquier esquema.

Por qué las pruebas no lo detectaron: el recorrido del flujo sustituía
`async_create_entry` por un doble, así que verificaba los datos que se le
pasaban pero no que ese camino se recorriera de verdad ni que la pantalla
anterior fuese usable. Ahora la prueba usa el `async_create_entry` real de
Home Assistant (con `flow_id`, `handler` y `context` puestos como hace el
gestor de flujos) y comprueba que el paso previo es un menú con las dos
opciones.

Se añadió además una prueba de los ficheros de traducción: valida el JSON y
que todo paso propio que pinta pantalla tenga su texto en los tres ficheros.
Salió de que, al editar los JSON con un heredoc, un `\n` se coló como texto
literal detrás del objeto y los dejó inválidos sin que nada lo avisara.

### 7.4 Un ciclo manual cancelaba el programado (v0.2.3)

Detectado al verificar el alta recién creada. La guarda que impide programar
dos ciclos para el mismo amanecer (§4.1) se apoyaba en `ultimo_ciclo`, que
se escribe en **cualquier** ejecución, también en la del servicio
`riego.ejecutar_ciclo`. Consecuencia: lanzar un ciclo a mano por la tarde
—lo natural para ver números durante la fase de simulación— marcaba el
amanecer siguiente como cumplido y el ciclo real se saltaba sin avisar.

Desde v0.2.4 la guarda usa `ultimo_ciclo_programado`, que solo escribe el
planificador. `ultimo_ciclo` se mantiene para el sensor «Último ciclo», que
sí debe reflejar también las ejecuciones manuales.

No hay riesgo de doble riego: el ciclo manual pone a cero el acumulado de
ET₀, así que el programado de esa madrugada encuentra un déficit nuevo de
casi cero y no envía nada.


### 7.5 Dos defectos de la estrategia de panel (v0.2.4)

Al crear el panel en la instalación real, la estrategia generó bien las
cuatro secciones pero con dos fallos visibles:

- **Una tarjeta «Error de configuración» por zona.** El tile del interruptor
  declaraba `features: [{type: "switch-toggle"}]`. Esa característica no
  existe en Home Assistant; para un switch es `toggle`.
- **La sección «Ajustes» vacía.** La tarjeta `entities` con los cuatro
  `number` sí se generaba con su contenido —comprobado ejecutando
  `ll-strategy-dashboard-riego.generate()` en la propia página— pero una
  tarjeta `entities` se colapsa dentro de una vista de tipo `sections`. Se
  sustituye por un tile por número con `numeric-input`.

Añadido de paso: los tiles muestran ahora el nombre sin el prefijo del
dispositivo. Con `has_entity_name`, el `friendly_name` es «Zona Frutales
Déficit acumulado», que en una columna estrecha se trunca y no se lee.

No hay forma de probar esto sin un navegador: la estrategia solo se ejecuta
en el frontend. Se verificó abriendo el panel y comparando antes y después.

### 7.6 Los avisos de Telegram no llegaban nunca (v0.3.0)

Encontrado revisando el log tras el primer ciclo real:

```
telegram.error.BadRequest: Can't parse entities:
can't find end of the entity starting at byte offset 198
```

El resumen de simulación incluye el resultado de cada zona en crudo:
`sin_riego`. Telegram interpreta `_` como marca de cursiva, y tres guiones
bajos —número impar— dejan la marca sin cerrar, así que **rechaza el mensaje
entero**. Ningún aviso llegó desde la puesta en marcha.

Corregido en dos capas: un diccionario de etiquetas legibles («sin riego» en
vez de `sin_riego`) y un saneado final que neutraliza `_ * ` [ ]` en
cualquier mensaje, venga de donde venga. Hay prueba que falla si un aviso
vuelve a contener esos caracteres.

### 7.7 «Próximo ciclo» se quedaba en desconocido tras regar

Una vez ejecutado el ciclo del día, la guarda de §7.4 impide reprogramar y
`_proximo` quedaba a `None`, de modo que el sensor mostraba «desconocido»
hasta que el planificador entraba en la ventana del amanecer siguiente, unas
veinte horas después. Ahora, cuando el ciclo ya está hecho, se estima el del
día siguiente; el planificador lo afina luego con el déficit real.

Detalle de proceso: el primer intento de este arreglo **no se aplicó** —la
sustitución de texto buscaba un `else:` que no existía y no falló, solo no
hizo nada—. Lo detectó la prueba. Desde entonces toda edición por sustitución
lleva un `assert` de que el patrón aparece.

### 7.8 Falsa alarma: los paneles en blanco

Tras un reinicio, **todos** los paneles Lovelace de la instalación aparecían
vacíos, incluidos los que no tienen nada que ver con esta integración. Se
verificó que las configuraciones estaban intactas (`lovelace/config` devolvía
las vistas correctas) y que `hui-panel-view` y `hui-sections-view` no
llegaban a definirse: el navegador conservaba un `app.js` cacheado por el
service worker que apuntaba a *chunks* de la versión anterior de Home
Assistant. Se resolvió desregistrando el service worker y vaciando las cachés
del navegador. No tenía relación con la integración.

Sí salió de ahí un fallo propio: `riego-strategy.js` registraba la **misma
clase** con dos nombres de custom element. El segundo `define()` lanza
«this constructor has already been used with this registry» y aborta el
módulo. Cada alias necesita su propia subclase.

### 7.9 `via_device` obsoleto en el registro de dispositivos

Home Assistant 2026.9 avisa en cada arranque de que la integración usa
`via_device` —la tupla `(dominio, identificador)`— para enlazar cada zona con
el dispositivo de sistema. Deja de funcionar en **2027.8**. El sustituto es
`via_device_id`, que es el **id de registro** del dispositivo padre, una
cadena, no una tupla.

Eso obliga a que el dispositivo «Balance Hídrico» exista **antes** de que se
creen las entidades de zona, cosa que antes no estaba garantizada: lo creaba
la primera entidad de sistema que se añadiera. Ahora se crea explícitamente
en `async_setup_entry`, antes de reenviar a las plataformas, y su id se
guarda en `coordinador.id_dispositivo_sistema`.

Si por lo que sea ese id no estuviera disponible, `info_zona` omite la clave
en lugar de enlazar mal: la zona aparecería como dispositivo suelto, que es
un fallo cosmético y no una excepción.
