"""Add one person to Dex's local user database (T39, ADR 0034).

    uv run python -m scripts.dex_add_user you@example.com [--username piero]

Asks for a password (typed twice, never shown or logged), hashes it with bcrypt, and
prints one line: `email:hash:username:userID`. Add it to DEX_STATIC_PASSWORDS in `.env`
(single-quoted: the hash contains `$`); more than one person is comma-separated. Dex
reads that variable at container start (dex/config.yaml.tpl) -- restart it
(`make up`) for a new or changed line to take effect.

`--username` is also what Superset's row-level security matches against (T41,
ADR 0036): defaulting it to the email, not the part before `@`, is deliberate -- no
`user_id` this project ever writes contains `@`, so someone you add with no
`--username` sees no data until you explicitly set it to a real one from the gold
tables (e.g. `--username piero`).
"""

import argparse
import getpass
import sys
import uuid
from collections.abc import Sequence

import bcrypt

_SEPARATOR_FREE = ":,\n"


def entry(email: str, password: str, username: str | None = None) -> str:
    """One `email:hash:username:userID` line for DEX_STATIC_PASSWORDS."""
    if any(c in email for c in _SEPARATOR_FREE):
        raise ValueError(f"email must not contain {_SEPARATOR_FREE!r}: {email!r}")
    name = username or email
    if any(c in name for c in _SEPARATOR_FREE):
        raise ValueError(f"username must not contain {_SEPARATOR_FREE!r}: {name!r}")
    digest = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    return f"{email}:{digest}:{name}:{uuid.uuid4()}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email")
    parser.add_argument(
        "--username", help="defaults to the email; set to a real user_id to grant data"
    )
    args = parser.parse_args(argv)

    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Password (again): "):
        print("the two passwords did not match.", file=sys.stderr)
        return 1

    try:
        line = entry(args.email, password, args.username)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2

    print("Add this to DEX_STATIC_PASSWORDS in .env (comma-separated for more people):")
    print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
