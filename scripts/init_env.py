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
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ACCOUNT_KEY_BYTES = 32
_SECRET_BYTES = 16
_GENERATED = (
    "PFP_ACCOUNT_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "PFP_PG_PASSWORD",
    "PFP_PG_BI_PASSWORD",
    "PFP_BI_DB_PASSWORD",
    "PFP_BI_ADMIN_PASSWORD",
    "PFP_BI_SECRET_KEY",
)


def render(template: str, user: str = "demo") -> str:
    """`template` (the text of `.env.example`) with its empty required values filled."""
    values = {name: secrets.token_hex(_SECRET_BYTES) for name in _GENERATED}
    values["PFP_ACCOUNT_KEY"] = secrets.token_hex(_ACCOUNT_KEY_BYTES)
    values["PFP_USER"] = user
    lines = []
    for line in template.splitlines():
        name, separator, value = line.partition("=")
        if separator and not line.lstrip().startswith("#") and name in values:
            if not value:
                line = f"{name}={values[name]}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=_ROOT / ".env")
    parser.add_argument("--user", default="demo", help="the name your data belongs to")
    args = parser.parse_args(argv)

    if args.out.exists():
        print(
            f"{args.out} already exists: not touching it (it holds your secrets).",
            file=sys.stderr,
        )
        return 1
    text = render((_ROOT / ".env.example").read_text(), args.user)
    # Created readable by you only from the first byte, not chmod-ed afterwards.
    descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(text)
    print(f"wrote {args.out} (mode 600) with generated secrets.")
    print("Superset login: user admin, password = PFP_BI_ADMIN_PASSWORD in that file.")
    print("For real data, back up PFP_ACCOUNT_KEY: losing it changes every account id.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
