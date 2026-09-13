# Setup

Steps to reproduce the project on another computer. Run them once, in order;
section 5 checks that everything came out right at the end.

## 1. Requirements

Versions the project was tested with. Newer versions usually work;
if something breaks, fall back to these.

| Program | Tested version | What for | Needed from |
|---|---|---|---|
| Windows + WSL2 with Ubuntu | Ubuntu 26.04 LTS, kernel 6.6 | Linux development environment | Start |
| Git | 2.53 | Version control | Start |
| curl | 8.18 | Download the uv installer | Start |
| uv | 0.12.13 | Installs Python and the libraries per `uv.lock` | Start |
| Python | 3.12.14 (installed by uv) | Project language | Start |
| pre-commit | 4.6.2 | Security guards and lint before every commit | Start |
| make | 4.4 | Check shortcuts (`make check-task`) | T4 |
| Docker Desktop | 4.43.2 (Engine 28.3.2, Compose 2.38) | Local S3 with SeaweedFS | T13 |
| Tesseract OCR + Spanish language pack | 5.5 | OCR for scanned PDFs | T11b |
| GitHub CLI (`gh`) | 2.46 | PRs from the terminal | Optional |

No need to install a system Python or Go: uv brings its own Python, and pre-commit
builds gitleaks on its own.

## 2. Windows: WSL2 and Docker Desktop

1. In an admin PowerShell: `wsl --install` (installs WSL2 with Ubuntu) and reboot.
2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and turn on
   **Settings → Resources → WSL integration** for your distro.
3. Inside Ubuntu, give yourself access to Docker without `sudo`:

   ```bash
   sudo usermod -aG docker "$USER"
   ```

   Then, in PowerShell, run `wsl --shutdown` and reopen Ubuntu so it picks up the group.

## 3. Ubuntu (WSL): system packages and uv

```bash
sudo apt update
sudo apt install -y git curl make tesseract-ocr tesseract-ocr-spa gh

# uv, at the tested version (installs into ~/.local/bin, no sudo needed)
curl -LsSf https://astral.sh/uv/0.12.13/install.sh | sh
```

Open a new terminal so `~/.local/bin` lands on your `PATH`.

## 4. Project

Clone inside the Linux filesystem (`~/…`), not under `/mnt/c`: it's much faster.

```bash
git clone https://github.com/PieroRios2000/personal-finance-platform.git
cd personal-finance-platform

uv sync --locked                    # Python 3.12 + every exact library from uv.lock
uv tool install pre-commit==4.6.2
pre-commit install                  # enables the hooks in this clone
pre-commit install-hooks            # downloads the hooks (gitleaks, ruff…) once

cp .env.example .env && chmod 600 .env   # fill in the values; .env never gets committed
```

Real PDFs live **outside the repo**, readable only by your user:

```bash
mkdir -p ~/finance-data/inbox/<user>    # per-user inbox, e.g. inbox/piero
chmod 700 ~/finance-data
# drop that user's PDFs there, from any bank, under any name, then:
chmod 600 ~/finance-data/inbox/*/*.pdf
```

Once processed (`pfp ingest`, from T12b and T14), each PDF gets filed into
`~/finance-data/raw/<user>/<bank>/<account>/<period>.pdf`; repeats go to `_duplicates/` and
unrecognized ones go to `_needs_review/`. A file is never deleted.

### Python libraries

They're consolidated in one place and all installed with `uv sync --locked`:

- `pyproject.toml`: the direct dependencies.
- `uv.lock`: the exact version (with a hash) of every library, including transitive ones.
  This is what guarantees every machine installs the exact same thing.

| Library | Pinned version | Type | What for |
|---|---|---|---|
| pydantic | 2.13.5 | runtime | Transaction models and validation |
| pikepdf | 10.13.0.post1 | runtime | Open and decrypt password-protected PDFs |
| pdfplumber | 0.11.10 | runtime | Read PDF text along with positions |
| fpdf2 | 2.8.8 | dev | Generate synthetic PDFs inside the tests |
| pytest | 9.1.1 | dev | Tests |
| pytest-cov | 7.1.0 | dev | Coverage |
| ruff | 0.16.7 | dev | Lint and format |
| mypy | 2.3.1 | dev | Types (strict mode) |
| diff-cover | 10.5.1 | dev | Coverage of changed lines against the base branch |
| import-linter | 2.15 | dev | Architecture contracts (who can import whom) |
| pip-audit | 2.10.1 | dev | Known vulnerabilities in dependencies |
| bandit | 1.9.4 | dev | Security issues in the code |

Don't use `pip install` or a `requirements.txt`: they drift out of sync with the lock. To add a
library: `uv add <lib>` (or `uv add --dev <lib>`), then commit `pyproject.toml` and `uv.lock`
together, updating this table.

## 5. Verification

```bash
make check-task                     # lint, format, types, tests, floor-guard and architecture
pre-commit run --all-files
docker run --rm hello-world         # Docker Desktop must be running
tesseract --list-langs              # should include "spa"
```

All green = the environment is ready.

## Known issues

| Symptom | Fix |
|---|---|
| `The command 'docker' could not be found in this WSL 2 distro` | Docker Desktop is closed or WSL integration is off (step 2) |
| Docker Desktop: `wsl-bootstrap … exit status 1` on startup | In PowerShell, `wsl --shutdown`, then reopen Docker Desktop; if it persists, `wsl --update` |
| `permission denied` on `/var/run/docker.sock` | Missing the `docker` group, or WSL wasn't restarted (section 2, step 3) |
| `gh pr edit` fails with a *Projects classic* error (gh 2.46) | Use `gh api --method PATCH repos/<owner>/<repo>/pulls/<n>`, or upgrade gh from cli.github.com |
| `gh run view --log` or `--log-failed` show nothing (gh 2.46) | Fetch the job's log from the API: `gh api repos/<owner>/<repo>/actions/jobs/<job_id>/logs` (the `job_id` shows up in `gh run view <run_id>`) |
| Files named `<PdfName>.pdf:Zone.Identifier` appear under `~/finance-data/` | Windows adds them when copying from File Explorer; delete them (`find ~/finance-data -name '*:Zone.Identifier' -delete`) — they're not part of the PDF |
