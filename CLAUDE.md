# Integracion_Riego

Repositorio de la integración custom de Home Assistant "Riego por Balance
Hídrico" de Maxi. Es la **fuente de verdad** del código y, a la vez, la
fuente desde la que HACS instala/actualiza la integración — este repo es
**público** a propósito, porque HACS solo puede leer repos públicos (no
soporta repos privados; se probó con `Integracion_Bomba_calor_predictor` y
da 404 incluso con GitHub autenticado).

## Entorno

- Repo local clonado en: `~/Downloads/GitHub/Integracion_Riego`
- El HA real está montado por Samba en el Mac:
  - `/Volumes/config/custom_components/riego` → donde HACS instala
    finalmente la integración
- Esta sesión de Claude Code **no tiene credenciales de GitHub** ni `gh`
  instalado: puede hacer `git add` y `git commit`, pero **no puede hacer
  `git push` ni crear el repositorio remoto**. Eso lo hace siempre el
  usuario, normalmente desde GitHub Desktop.
- Un clasificador de seguridad automático puede bloquear `git add` sobre
  archivos cuyo nombre suene a secreto aunque no tengan datos sensibles
  reales. Si pasa, que el usuario haga ese `git add` puntual él mismo.

## Estructura

```
custom_components/riego/     manifest.json, __init__.py, coordinator.py, et0.py...
custom_components/riego/frontend/riego-strategy.js   estrategia de panel
custom_components/riego/brand/    icon.png e icon@2x.png: el icono de la integración
tools/generar_icono.py       genera esos PNG (Pillow; el venv de pruebas ya lo trae)
docs/DECISIONES.md           historial de decisiones, NO va en custom_components
hacs.json
README.md
```

`docs/DECISIONES.md` está fuera de `custom_components/riego/` a propósito:
cuando HACS instala la integración copia esa carpeta entera a
`/config/custom_components/riego`, y no tiene sentido que la documentación
de decisiones viaje a la instalación real de HA.

## Estado actual: en producción desde el 16/09/2026

Esta integración **riega de verdad**: sustituyó al paquete YAML antiguo
`packages/riego/` y a la automatización «Riego — Ciclo diario al amanecer». El
corte se hizo el 16/09/2026 a las 15:33 (se apagó la automatización antigua y
el modo simulación) y después el sistema viejo se ha retirado por completo: el
20/09 ya no existían el paquete, la automatización ni los helpers, y el 25/09
tampoco el panel antiguo, las entidades huérfanas ni sus estadísticas.

Consecuencias para quien edite esto:

- **Un cambio en `coordinator.py` actúa sobre válvulas reales.** El modo
  simulación está apagado. Para probar un cambio que toque el ciclo, o se
  enciende `switch.balance_hidrico_modo_simulacion` o se prueba con los tests;
  ojo, en simulación el coordinador sí suma a `litros_de_la_temporada` y
  consume el déficit (`docs/DECISIONES.md` §7.14).
- **No hay camino de vuelta dentro de HA.** Esta sesión no guardó copia de los
  ficheros del paquete antiguo, y el respaldo automático del MCP no cubre
  subcarpetas. El procedimiento de migración, ya histórico, está en §5.
- **El riego manual por litros que daba `mqtt.yaml` ya no existe**
  (`number.riego_*_litros`). Ahora se hace con el servicio `riego.regar_zona`.
- **Dos automatizaciones de Telegram viven fuera de este repo**, en el
  `automations.yaml` de HA: «Notificaciones Riego Telegram 1» y «Vigilancia de
  caudal anómalo». Sus umbrales de volumen y de tiempo pasando agua se derivaron
  del techo de cada zona: si cambias un techo, revísalos (§7.17).
- **No te fíes de `switch.riego_*` para saber si una válvula riega**: puede
  quedarse en `on` horas después de cerrar (§7.22). Lo fiable es el caudal
  (`sensor.riego_*_flow`, que es lo que usa la integración) o
  `binary_sensor.riego_*_valve_work_state`, que informa la propia válvula.

## Contexto importante del cálculo

La plantilla YAML original tenía un error de unidades en la constante
psicrométrica (`P` en hPa donde FAO-56 pide kPa). **No es un factor
constante**: infla ×10 el término aerodinámico y ×3,3 el denominador, así que
la fórmula vieja subestimaba la ET₀ con viento flojo y la sobrestimaba con
viento fuerte (×1,41 y ×1,68 en dos días de calma de septiembre, ×0,97 en un
día ventoso de agosto). Decir «subestimaba un 40 %» o «riega un 70 % más» es
incorrecto. Datos y razonamiento en `docs/DECISIONES.md` §2.1.

El parámetro por zona `coeficiente de ajuste` está en **1,0** en las tres
zonas (dosis FAO-56 íntegra): lo decidió Maxi antes del corte, es decisión
suya y no técnica. Queda por revisar en abril/mayo de 2027 con una temporada
completa, y por comprobar con pala (25–30 cm en el borde del bulbo húmedo de
Frutales, 24 h después de un riego). Ver §4.3.

## Flujo para editar la integración

1. Editar los archivos **en el repo**, dentro de `custom_components/riego/`.
2. Commit en el repo (yo puedo). Push lo hace el usuario.
3. Subir el número de `version` en `manifest.json` cuando el cambio esté
   listo para probarse — HACS detecta la actualización por ese número.
4. El usuario actualiza desde HACS y reinicia HA para probar.
5. Si algo falla, se corrige, se sube la versión otra vez, commit, push,
   actualizar, reiniciar.

No copiar directamente en `/Volumes/config/custom_components/riego` sin
antes editar en el repo — se perdería el historial de lo que realmente se
probó.

## Probar sin tocar el HA real

Un fallo del flujo de configuración (v0.1.0) llegó a la instalación real
porque no había forma de verificarlo antes. Ahora sí la hay:

```bash
python3 -m venv /tmp/hav
/tmp/hav/bin/pip install homeassistant==2026.9.2 paho-mqtt
/tmp/hav/bin/python tests/test_riego.py
node tests/test_estrategia.mjs
```

El segundo no necesita el venv: ejecuta la estrategia de panel con un
`hass` sintético y comprueba las tarjetas que genera. Existe porque un
fallo ahí no se ve — una tarjeta con una opción inválida se pinta sin
error pero deja el control inservible.

Dos trampas de HA 2026.9 que costaron un rato:

- Los esquemas de los flujos ya no se serializan con `voluptuous_serialize`,
  sino con `to_field_list` de **probatio**, que sustituye a `voluptuous`.
- Hay que importar `homeassistant` **antes** que cualquier cosa que importe
  `voluptuous`, o `install_as_voluptuous()` no llega a tiempo y las
  referencias apuntan al paquete equivocado.

## Módulo de cálculo

`custom_components/riego/et0.py` no importa nada de Home Assistant a
propósito: se puede ejecutar y validar de forma aislada con `python3`, que
es como se comprobó contra los datos horarios reales de la estación durante
la revisión inicial.
