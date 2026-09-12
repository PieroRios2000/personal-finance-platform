# personal-finance-platform

## Desarrollo

Prepara el entorno y activa las guardas de seguridad antes del primer commit:

```bash
uv sync                # Python 3.12 y dependencias según uv.lock
uv tool install pre-commit
pre-commit install
cp .env.example .env   # rellena los valores; .env nunca se sube a Git
```