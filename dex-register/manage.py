"""Operator commands for Dex accounts (ADR 0039), run inside the dex-register container,
the only place that can reach Dex's gRPC API (never published):

    make dex-add-user EMAIL=you@example.com [USERNAME=piero]
    make dex-scope EMAIL=you@example.com USERNAME=piero

`add` asks for a password (typed twice, never shown or logged) and creates the account
straight in Dex's storage, like the sign-up page but without the invite code (you are
already on the machine). `scope` sets the `user_id` the account is filtered to in
Superset (T41, ADR 0036) and leaves its password alone.

The username defaults to the full email, not the part before `@`, on purpose: no
`user_id` this project writes contains `@`, so an account with no explicit username
sees no data until you point it at a real one from the gold tables.
"""

import argparse
import getpass
import sys
from collections.abc import Sequence
from uuid import uuid4

import bcrypt
import grpc
from api_pb2 import CreatePasswordReq, Password, UpdatePasswordReq
from api_pb2_grpc import DexStub
from registration import EMAIL, validate_password


def _stub() -> DexStub:
    return DexStub(grpc.insecure_channel("dex:5557"))


def add(email: str, username: str | None) -> int:
    if not EMAIL.fullmatch(email):
        print(f"{email!r} does not look like an email address.", file=sys.stderr)
        return 2
    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Password (again): ")
    error = validate_password(password, confirm)
    if error:
        print(error, file=sys.stderr)
        return 1
    digest = bcrypt.hashpw(password.encode(), bcrypt.gensalt())
    response = _stub().CreatePassword(
        CreatePasswordReq(
            password=Password(
                email=email,
                hash=digest,
                username=username or email,
                user_id=str(uuid4()),
            )
        )
    )
    if response.already_exists:
        print(
            f"{email} already has an account: `make dex-scope` changes its username.",
            file=sys.stderr,
        )
        return 1
    print(f"Created {email} (username: {username or email}).")
    return 0


def scope(email: str, username: str) -> int:
    response = _stub().UpdatePassword(
        UpdatePasswordReq(email=email, new_username=username)
    )
    if response.not_found:
        print(f"No account for {email}.", file=sys.stderr)
        return 1
    print(f"{email} now sees the data of user_id {username}.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    add_parser = commands.add_parser("add", help="create an account")
    add_parser.add_argument("email")
    add_parser.add_argument("--username")
    scope_parser = commands.add_parser("scope", help="set an account's user_id")
    scope_parser.add_argument("email")
    scope_parser.add_argument("username")
    args = parser.parse_args(argv)

    try:
        if args.command == "add":
            return add(args.email, args.username)
        return scope(args.email, args.username)
    except grpc.RpcError:
        print("Dex is not reachable: is the stack up (`make up`)?", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
