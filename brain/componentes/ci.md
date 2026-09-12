---
tipo: componente
fase: 1
estado: en-curso
tarea: T5
---

# CI

Controles automáticos de GitHub Actions en cada PR. Hoy solo existe la política de ramas; el resto
llega en T5, T15, T17 y T17b (detalle en el [plan](../../tasks/plan.md)).

## Piezas

| Pieza | Estado | Qué hace |
|---|---|---|
| [`branch-policy.yml`](../../.github/workflows/branch-policy.yml) | Construido | Solo `develop` del propio repo puede abrir PRs hacia `main`; check obligatorio `check-source-branch` en el ruleset de `main` y `develop` |
| Checks de calidad (T5) | Planificado | Lint, tipos, tests con cobertura, seguridad y arquitectura; fallos anotados en la línea del PR |
| CI por impacto (T15, ADR 0008) | Planificado | Los jobs caros corren solo si el cambio los afecta |
| Entorno efímero (T17, T17b, ADR 0007) | Planificado | Plataforma temporal por PR con datos sintéticos y comparación base vs PR |

## Detalles que no se deben romper

- `branch-policy` usa `pull_request_target`: corre la versión del workflow que ya está en el repo, así
  que un PR no puede editarlo para aprobarse; no hace checkout del código del PR ni recibe permisos.
- Nunca se salta con `if`: un job saltado cuenta como exitoso aunque sea obligatorio.
- Nada de filtros `paths` en workflows con checks obligatorios: dejan el check en "Pending" y
  bloquean el merge.

## Cómo se usa y cómo se verifica

`gh pr checks <n>` y `gh run view <run_id>`; el log de un job fallido se pide a la API (ver
"Problemas conocidos" en [SETUP.md](../../SETUP.md)).

## Relacionado

- [Proyecto Python](proyecto-python.md) — lo que el CI valida.
- [Guardas de seguridad](guardas-de-seguridad.md) — los hooks locales que el CI hará obligatorios.
- [Fase 1](../fases/fase-1.md)
