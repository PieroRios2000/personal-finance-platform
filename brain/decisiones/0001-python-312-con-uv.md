---
tipo: decision
fase: 1
estado: aceptada
fecha: 2026-09-12
---

# ADR 0001: Python 3.12 gestionado con uv

## Contexto

El sistema trae Python 3.14. Es muy nuevo para parte del stack: dbt lo soporta hace poco y con
caveats de dependencias, y las herramientas de las fases 2 y 3 suelen ir detrás. Además, el proyecto
tiene que reproducirse igual en otra computadora sin depender del Python del sistema.

## Decisión

Python 3.12 instalado y gestionado por uv, con las dependencias en `pyproject.toml` y las versiones
exactas en `uv.lock`, que se versiona. Todo se instala con `uv sync --locked`.

## Alternativas consideradas

- **Python 3.14 del sistema**: riesgo de incompatibilidades con dbt y con herramientas de fases
  posteriores.
- **pyenv + pip-tools**: dos herramientas para lo mismo, y pyenv compila Python desde el código
  fuente, lo que exige dependencias del sistema.
- **conda**: pesado y con su propio ecosistema de paquetes, innecesario en un proyecto solo Python.

## Consecuencias

- Una sola herramienta instala Python y las librerías, sin sudo (ver [SETUP.md](../../SETUP.md)).
- `uv.lock` garantiza las mismas versiones en todas las máquinas y en el CI; se sube junto con
  `pyproject.toml`. Nada de `pip install` ni `requirements.txt`.
- Pasar a un Python más nuevo es cambiar `.python-version` y `requires-python`, y volver a pasar los checks.

## Relacionado

- [Proyecto Python](../componentes/proyecto-python.md) — donde se aplica.
- [Fase 1](../fases/fase-1.md)
