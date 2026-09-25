"""Write a `.env` a clean clone can start from, with every secret generated (T33).

    uv run python -m scripts.init_env [--out .env] [--user demo]

Fills the variables that need a value to bring the platform up (the user name, the
account HMAC key, the local S3 pair, the Postgres and Superset passwords) from
`.env.example`, keeps everything else as the template has it (comments, ports, the alert
and PDF-password variables left empty), and writes the file readable by you only. It
never overwrites an existing `.env`: that file holds your real secrets (the account key
must be backed up). The secrets are hexadecimal, so the shell, Compose and dbt read them
back unchanged.
"""

import argparse
import os
import re
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ACCOUNT_KEY_BYTES = 32
_SECRET_BYTES = 16
_SAFE_USER = re.compile(r"[A-Za-z0-9_-]+")
# Published host ports, moved together for a second environment on the same machine.
_PORTS = (
    "SEAWEEDFS_S3_PORT",
    "PFP_PG_PORT",
    "PFP_BI_PORT",
    "OPENMETADATA_PORT",
    "PFP_DEX_PORT",
)
_GENERATED = (
    "PFP_ACCOUNT_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "PFP_PG_PASSWORD",
    "PFP_PG_BI_PASSWORD",
    "PFP_BI_DB_PASSWORD",
    "PFP_BI_ADMIN_PASSWORD",
    "PFP_BI_SECRET_KEY",
    "PFP_BI_OAUTH_CLIENT_SECRET",
)


def render(template: str, user: str = "demo", port_offset: int = 0) -> str:
    """`template` (the text of `.env.example`) with its empty required values filled and
    every published port moved by `port_offset` (another environment, ADR 0033)."""
    values = {name: secrets.token_hex(_SECRET_BYTES) for name in _GENERATED}
    values["PFP_ACCOUNT_KEY"] = secrets.token_hex(_ACCOUNT_KEY_BYTES)
    values["PFP_USER"] = user
    lines = []
    for line in template.splitlines():
        name, separator, value = line.partition("=")
        if separator and not line.lstrip().startswith("#"):
            if name in values and not value:
                line = f"{name}={values[name]}"
            elif name in _PORTS:
                line = f"{name}={int(value) + port_offset}"
            elif name in ("AWS_ENDPOINT_URL", "DEX_ISSUER"):
                prefix, _, port = value.rpartition(":")
                path = ""
                if "/" in port:
                    port, _, rest = port.partition("/")
                    path = f"/{rest}"
                line = f"{name}={prefix}:{int(port) + port_offset}{path}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=_ROOT / ".env")
    parser.add_argument("--user", default="demo", help="the name your data belongs to")
    parser.add_argument(
        "--port-offset",
        type=int,
        default=0,
        help="move every published port (a second environment on this machine)",
    )
    args = parser.parse_args(argv)

    if not _SAFE_USER.fullmatch(args.user):
        print(
            "--user must be letters, digits, `_` or `-`: it is a folder name and is "
            "written into a file the shell sources.",
            file=sys.stderr,
        )
        return 2
    text = render((_ROOT / ".env.example").read_text(), args.user, args.port_offset)
    # Created readable by you only from the first byte, not chmod-ed afterwards, and
    # never over an existing file (O_EXCL): that file holds your real secrets.
    try:
        descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(
            f"{args.out} already exists: not touching it (it holds your secrets).",
            file=sys.stderr,
        )
        return 1
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)
    print(f"wrote {args.out} (mode 600) with generated secrets.")
    print("Sign in to Superset with your email: `make dex-add-user EMAIL=you@ex.com`.")
    print(
        f"PFP_USER={args.user}: use another name for real statements (demo mixes in)."
    )
    print("For real data, back up PFP_ACCOUNT_KEY: losing it changes every account id.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
