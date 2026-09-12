# Puesta en marcha

Pasos para reproducir el proyecto en otra computadora. Se ejecutan una sola vez y en orden;
al terminar, la sección 5 comprueba que todo quedó bien.

## 1. Requisitos

Versiones con las que se probó el proyecto. Versiones más nuevas suelen funcionar;
si algo falla, vuelve a estas.

| Programa | Versión probada | Para qué | Se usa desde |
|---|---|---|---|
| Windows + WSL2 con Ubuntu | Ubuntu 26.04 LTS, kernel 6.6 | Entorno Linux de desarrollo | Inicio |
| Git | 2.53 | Control de versiones | Inicio |
| curl | 8.18 | Descargar el instalador de uv | Inicio |
| uv | 0.12.13 | Instala Python y las librerías según `uv.lock` | Inicio |
| Python | 3.12.14 (lo instala uv) | Lenguaje del proyecto | Inicio |
| pre-commit | 4.6.2 | Guardas de seguridad y lint antes de cada commit | Inicio |
| make | 4.4 | Atajos de checks (`make check-task`) | T4 |
| Docker Desktop | 4.43.2 (Engine 28.3.2, Compose 2.38) | S3 local con SeaweedFS | T13 |
| Tesseract OCR + idioma español | 5.5 | OCR de los PDFs escaneados | T11b |
| GitHub CLI (`gh`) | 2.46 | PRs desde la terminal | Opcional |

No hace falta instalar Python del sistema ni Go: uv trae su propio Python y pre-commit
compila gitleaks por su cuenta.

## 2. Windows: WSL2 y Docker Desktop

1. En PowerShell como administrador: `wsl --install` (instala WSL2 con Ubuntu) y reinicia.
2. Instala [Docker Desktop](https://www.docker.com/products/docker-desktop/) y activa
   **Settings → Resources → WSL integration** para tu distro.
3. Dentro de Ubuntu, da acceso a Docker sin `sudo`:

   ```bash
   sudo usermod -aG docker "$USER"
   ```

   Luego, en PowerShell, `wsl --shutdown` y vuelve a abrir Ubuntu para que tome el grupo.

## 3. Ubuntu (WSL): paquetes del sistema y uv

```bash
sudo apt update
sudo apt install -y git curl make tesseract-ocr tesseract-ocr-spa gh

# uv, en la versión probada (se instala en ~/.local/bin, sin sudo)
curl -LsSf https://astral.sh/uv/0.12.13/install.sh | sh
```

Abre una terminal nueva para que `~/.local/bin` quede en el `PATH`.

## 4. Proyecto

Clona dentro del disco de Linux (`~/…`), no en `/mnt/c`: es mucho más rápido.

```bash
git clone https://github.com/PieroRios2000/personal-finance-platform.git
cd personal-finance-platform

uv sync --locked                    # Python 3.12 + todas las librerías exactas de uv.lock
uv tool install pre-commit==4.6.2
pre-commit install                  # activa los hooks en este clon
pre-commit install-hooks            # descarga los hooks (gitleaks, ruff…) una vez

cp .env.example .env && chmod 600 .env   # rellena los valores; .env nunca se sube a Git
```

Los PDFs reales viven **fuera del repo**, solo con permisos para tu usuario:

```bash
mkdir -p ~/finance-data/inbox/<usuario>    # bandeja por usuario, p. ej. inbox/piero
chmod 700 ~/finance-data
# deja ahí los PDFs de ese usuario, de cualquier banco y con cualquier nombre, y luego:
chmod 600 ~/finance-data/inbox/*/*.pdf
```

Al procesarlos (`pfp ingest`, desde T12b y T14), cada PDF se archiva en
`~/finance-data/raw/<usuario>/<banco>/<cuenta>/<periodo>.pdf`; los repetidos van a `_duplicados/` y los
que no se reconocen, a `_por_clasificar/`. Nunca se borra un archivo.

### Librerías de Python

Están consolidadas en un solo lugar y se instalan todas con `uv sync --locked`:

- `pyproject.toml`: las dependencias directas.
- `uv.lock`: la versión exacta (con hash) de cada librería, incluidas las indirectas.
  Es lo que garantiza que todas las computadoras instalen lo mismo.

| Librería | Versión fijada | Tipo | Para qué |
|---|---|---|---|
| pydantic | 2.13.5 | runtime | Modelos y validación de transacciones |
| pikepdf | 10.13.0.post1 | runtime | Abrir y descifrar los PDFs con contraseña |
| pdfplumber | 0.11.10 | runtime | Leer el texto de los PDFs con sus posiciones |
| fpdf2 | 2.8.8 | dev | Generar PDFs sintéticos dentro de los tests |
| pytest | 9.1.1 | dev | Tests |
| pytest-cov | 7.1.0 | dev | Cobertura |
| ruff | 0.16.7 | dev | Lint y formato |
| mypy | 2.3.1 | dev | Tipos (modo estricto) |
| diff-cover | 10.5.1 | dev | Cobertura de las líneas cambiadas contra la rama base |
| import-linter | 2.15 | dev | Contratos de arquitectura (quién importa a quién) |
| pip-audit | 2.10.1 | dev | Vulnerabilidades conocidas en las dependencias |
| bandit | 1.9.4 | dev | Problemas de seguridad en el código |

No uses `pip install` ni un `requirements.txt`: se desalinean del lock. Para agregar una
librería: `uv add <lib>` (o `uv add --dev <lib>`), y se suben juntos `pyproject.toml` y
`uv.lock`, actualizando esta tabla.

## 5. Verificación

```bash
make check-task                     # lint, formato, tipos, tests, floor-guard y arquitectura
pre-commit run --all-files
docker run --rm hello-world         # Docker Desktop debe estar abierto
tesseract --list-langs              # debe incluir "spa"
```

Todo en verde = el entorno está listo.

## Problemas conocidos

| Síntoma | Solución |
|---|---|
| `The command 'docker' could not be found in this WSL 2 distro` | Docker Desktop está cerrado o la integración WSL está desactivada (paso 2) |
| Docker Desktop: `wsl-bootstrap … exit status 1` al arrancar | En PowerShell `wsl --shutdown` y vuelve a abrir Docker Desktop; si persiste, `wsl --update` |
| `permission denied` en `/var/run/docker.sock` | Falta el grupo `docker` o no se reinició WSL (sección 2, punto 3) |
| `gh pr edit` falla con un error de *Projects classic* (gh 2.46) | Usa `gh api --method PATCH repos/<owner>/<repo>/pulls/<n>` o actualiza gh desde cli.github.com |
| `gh run view --log` o `--log-failed` no muestran nada (gh 2.46) | Pide el log del job a la API: `gh api repos/<owner>/<repo>/actions/jobs/<job_id>/logs` (el `job_id` aparece en `gh run view <run_id>`) |
