"""Self-service Dex registration (T40, ADR 0035): a friendly page so a new person can
pick their own email and password, gated by a shared invite code, instead of the
operator running `make dex-add-user` for them. Creates the account directly in Dex's
storage over its gRPC API (`CreatePassword`) -- the same store a restart would read
`DEX_STATIC_PASSWORDS` into, but this one takes effect immediately, no restart, because
it writes past the read-only, config-seeded overlay straight to the underlying storage
(confirmed by creating a user this way and logging in with it right after, in a
throwaway Dex, before wiring this up: see the PR).

One page at "/": GET shows the form, POST validates and creates the account. `api_pb2*`
are generated from `api.proto` at image build time (Dockerfile), never committed.
"""

import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs
from uuid import uuid4

import bcrypt
import grpc
from api_pb2 import CreatePasswordReq, Password
from api_pb2_grpc import DexStub
from registration import Throttle, validate

_INVITE_CODE = os.environ["PFP_DEX_INVITE_CODE"]
_GRPC_ADDR = os.environ.get("PFP_DEX_GRPC_ADDR", "dex:5557")
_THROTTLE = Throttle()

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Sign up</title>
<style>
  body {{ font-family: sans-serif; max-width: 28rem; margin: 3rem auto;
    padding: 0 1rem; }}
  label {{ display: block; margin-top: 1rem; }}
  input {{ width: 100%; padding: 0.4rem; box-sizing: border-box; }}
  button {{ margin-top: 1.5rem; padding: 0.5rem 1.5rem; }}
  .error {{ color: #b91c1c; }}
</style>
</head>
<body>
<h1>Sign up</h1>
{message}
<form method="post">
  <label>Email <input type="email" name="email" required></label>
  <label>Password <input type="password" name="password" required></label>
  <label>Password, again <input type="password" name="confirm" required></label>
  <label>Invite code <input type="text" name="invite_code" required></label>
  <button type="submit">Create account</button>
</form>
</body>
</html>
"""


def _page(message: str = "") -> bytes:
    return _PAGE.format(message=message).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        self._respond(_page())

    def do_POST(self) -> None:
        if self.path != "/":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", "0"))
        fields = {
            key: values[0]
            for key, values in parse_qs(self.rfile.read(length).decode()).items()
        }
        # Cloudflare Tunnel (and any reverse proxy) puts the real visitor's address in
        # this header; self.client_address would otherwise be the proxy's.
        ip = self.headers.get("CF-Connecting-IP", self.client_address[0])

        if _THROTTLE.blocked(ip):
            self._respond(_page('<p class="error">Too many attempts. Try later.</p>'))
            return

        error = validate(
            fields.get("email", ""),
            fields.get("password", ""),
            fields.get("confirm", ""),
            fields.get("invite_code", ""),
            _INVITE_CODE,
        )
        if error:
            _THROTTLE.record_failure(ip)
            self._respond(_page(f'<p class="error">{error}</p>'))
            return

        email = fields["email"]
        digest = bcrypt.hashpw(fields["password"].encode(), bcrypt.gensalt())
        stub = DexStub(grpc.insecure_channel(_GRPC_ADDR))
        response = stub.CreatePassword(
            CreatePasswordReq(
                password=Password(
                    email=email,
                    hash=digest,
                    username=email.split("@", 1)[0],
                    user_id=str(uuid4()),
                )
            )
        )
        if response.already_exists:
            error = '<p class="error">That email is already signed up.</p>'
            self._respond(_page(error))
            return
        self._respond(_page("<p>Account created. You can sign in now.</p>"))

    def _respond(self, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 5559), Handler).serve_forever()
