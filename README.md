# personal-finance-platform

## Desarrollo

Activa las guardas de seguridad antes del primer commit:

```bash
uv tool install pre-commit
pre-commit install
cp .env.example .env   # rellena los valores; .env nunca se sube a Git
```