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
docs/DECISIONES.md           historial de decisiones, NO va en custom_components
hacs.json
README.md
```

`docs/DECISIONES.md` está fuera de `custom_components/riego/` a propósito:
cuando HACS instala la integración copia esa carpeta entera a
`/config/custom_components/riego`, y no tiene sentido que la documentación
de decisiones viaje a la instalación real de HA.

## Qué sustituye esta integración

El paquete YAML `packages/riego/` del HA de casa (helpers.yaml, mqtt.yaml,
riego_et0.yaml, riego_sistema.yaml) más la automatización maestra
«Riego — Ciclo diario al amanecer». **No se ha borrado nada**: la migración
prevista es convivencia en modo simulación primero. El procedimiento
completo está en `docs/DECISIONES.md` §5.

Mientras dure la convivencia, el sistema antiguo se pausa apagando **solo**
`automation.riego_ciclo_diario_al_amanecer`. El resto del paquete es inerte.

## Contexto importante del cálculo

La plantilla YAML original tenía un error de unidades en la constante
psicrométrica (`P` en hPa donde FAO-56 pide kPa) que subestimaba la ET₀ un
~40 %. Esta integración lo corrige, así que **los litros que propone son
mayores que los del sistema antiguo**. El parámetro por zona
`coeficiente de ajuste` existe justamente para decidir cuánto de esa
corrección se aplica al riego real. Ver `docs/DECISIONES.md` §2.1 y §4.3
antes de tocar nada de esto.

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

## Módulo de cálculo

`custom_components/riego/et0.py` no importa nada de Home Assistant a
propósito: se puede ejecutar y validar de forma aislada con `python3`, que
es como se comprobó contra los datos horarios reales de la estación durante
la revisión inicial.
