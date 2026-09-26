"""Self-service Dex accounts (T40, ADR 0035; password reset T43, ADR 0038): a friendly
page so a new person can pick their own email and password, gated by a shared invite
code, instead of the operator running `make dex-add-user` for them -- and a way back in
for someone who forgot the password. Talks to Dex's storage over its gRPC API
(`CreatePassword`, `UpdatePassword`, `ListPasswords`); a write takes effect immediately,
no restart (confirmed by creating a user this way and logging in with it right after, in
a throwaway Dex, before wiring this up: see the PR).

Pages: "/" (sign up), "/forgot" (asks for an email, sends a link), "/reset?token=..."
(the link: a new password). `api_pb2*` are generated from `api.proto` at image build
time (Dockerfile), never committed.
"""

import html
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import bcrypt
import grpc
from api_pb2 import (
    CreatePasswordReq,
    ListPasswordReq,
    Password,
    UpdatePasswordReq,
)
from api_pb2_grpc import DexStub
from registration import EMAIL, Throttle, validate, validate_password
from reset import Mailer, TokenStore

_INVITE_CODE = os.environ["PFP_DEX_INVITE_CODE"]
_GRPC_ADDR = os.environ.get("PFP_DEX_GRPC_ADDR", "dex:5557")
_PUBLIC_URL = os.environ.get("PFP_REGISTER_PUBLIC_URL", "").rstrip("/")
_MAILER = Mailer.from_env(os.environ)
_THROTTLE = Throttle()
_FORGOT_BY_IP = Throttle()
_FORGOT_BY_EMAIL = Throttle(max_attempts=3)
_TOKENS = TokenStore()

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
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
<h1>{title}</h1>
{message}
{form}
</body>
</html>
"""

_SIGN_UP_FORM = """<form method="post">
  <label>Email <input type="email" name="email" required></label>
  <label>Password <input type="password" name="password" required></label>
  <label>Password, again <input type="password" name="confirm" required></label>
  <label>Invite code <input type="text" name="invite_code" required></label>
  <button type="submit">Create account</button>
</form>
<p><a href="/forgot">Forgot your password?</a></p>"""

_FORGOT_FORM = """<form method="post">
  <label>Email <input type="email" name="email" required></label>
  <button type="submit">Send me a link</button>
</form>"""

_RESET_FORM = """<form method="post">
  <input type="hidden" name="token" value="{token}">
  <label>New password <input type="password" name="password" required></label>
  <label>Password, again <input type="password" name="confirm" required></label>
  <button type="submit">Change password</button>
</form>"""

_ERROR = '<p class="error">{}</p>'
_LATER = "Try again in a moment."
_EXPIRED = "That link is invalid or has expired. Ask for a new one."


def _page(title: str, message: str = "", form: str = "") -> bytes:
    return _PAGE.format(title=title, message=message, form=form).encode()


def _sign_up(message: str = "") -> bytes:
    return _page("Sign up", message, _SIGN_UP_FORM)


def _forgot(message: str = "") -> bytes:
    return _page("Forgot your password", message, _FORGOT_FORM)


def _reset(token: str, message: str = "") -> bytes:
    form = _RESET_FORM.format(token=html.escape(token, quote=True))
    return _page("Choose a new password", message, form)


def _stub() -> DexStub:
    return DexStub(grpc.insecure_channel(_GRPC_ADDR))


def _send_reset_link(email: str) -> None:
    """Runs in a thread, so the page answers in the same time whether or not the email
    has an account (and however long SMTP takes). Names no one in its failures."""
    if _MAILER is None:
        return
    try:
        listed = _stub().ListPasswords(ListPasswordReq()).passwords
        if not any(p.email.lower() == email.lower() for p in listed):
            return
        token = _TOKENS.issue(email)
        _MAILER.send(email, f"{_PUBLIC_URL}/reset?token={token}")
    except (grpc.RpcError, OSError) as error:
        print(f"reset link not sent: {type(error).__name__}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/":
            self._respond(_sign_up())
        elif url.path == "/forgot":
            self._respond(_forgot(self._forgot_unavailable()))
        elif url.path == "/reset":
            token = parse_qs(url.query).get("token", [""])[0]
            if _TOKENS.peek(token) is None:
                self._respond(_forgot(_ERROR.format(_EXPIRED)))
            else:
                self._respond(_reset(token))
        else:
            self._not_found()

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        fields = {
            key: values[0]
            for key, values in parse_qs(self.rfile.read(length).decode()).items()
        }
        # Cloudflare Tunnel (and any reverse proxy) puts the real visitor's address in
        # this header; self.client_address would otherwise be the proxy's.
        ip = self.headers.get("CF-Connecting-IP", self.client_address[0])
        path = urlsplit(self.path).path
        if path == "/":
            self._post_sign_up(fields, ip)
        elif path == "/forgot":
            self._post_forgot(fields, ip)
        elif path == "/reset":
            self._post_reset(fields)
        else:
            self._not_found()

    def _post_sign_up(self, fields: dict[str, str], ip: str) -> None:
        if _THROTTLE.blocked(ip):
            self._respond(_sign_up(_ERROR.format("Too many attempts. Try later.")))
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
            self._respond(_sign_up(_ERROR.format(error)))
            return

        email = fields["email"]
        digest = bcrypt.hashpw(fields["password"].encode(), bcrypt.gensalt())
        try:
            response = _stub().CreatePassword(
                CreatePasswordReq(
                    password=Password(
                        email=email,
                        hash=digest,
                        # Not the part before @: Superset's row-level security (T41,
                        # ADR 0036) matches this against a real user_id, and no
                        # user_id this project writes contains "@" -- a self-
                        # registered account sees no data until the operator
                        # explicitly re-scopes it (make dex-add-user --username).
                        username=email,
                        user_id=str(uuid4()),
                    )
                )
            )
        except grpc.RpcError:
            # Dex unreachable, restarting, or similar: an unhandled exception here
            # would crash the request mid-response (ERR_EMPTY_RESPONSE in the
            # browser) and print a traceback that tells a stranger with the invite
            # code more than they need to know about this machine.
            self._respond(_sign_up(_ERROR.format(_LATER)), status=503)
            return
        if response.already_exists:
            self._respond(_sign_up(_ERROR.format("That email is already signed up.")))
            return
        self._respond(_sign_up("<p>Account created. You can sign in now.</p>"))

    def _forgot_unavailable(self) -> str:
        if _MAILER is None or not _PUBLIC_URL:
            return _ERROR.format(
                "Password reset by email is not set up here. Ask whoever runs this."
            )
        return ""

    def _post_forgot(self, fields: dict[str, str], ip: str) -> None:
        unavailable = self._forgot_unavailable()
        if unavailable:
            self._respond(_forgot(unavailable))
            return
        email = fields.get("email", "").strip()
        # Every submission counts, valid or not: the page is public and sends mail.
        by_ip = _FORGOT_BY_IP.blocked(ip)
        _FORGOT_BY_IP.record_failure(ip)
        if by_ip:
            self._respond(_forgot(_ERROR.format("Too many attempts. Try later.")))
            return
        by_email = _FORGOT_BY_EMAIL.blocked(email.lower())
        _FORGOT_BY_EMAIL.record_failure(email.lower())
        if not by_email and EMAIL.fullmatch(email):
            threading.Thread(
                target=_send_reset_link, args=(email,), daemon=True
            ).start()
        # The same answer for every email, so this page cannot be used to find out who
        # has an account.
        self._respond(
            _forgot(
                "<p>If that email has an account, we sent it a link "
                "(valid for 30 minutes).</p>"
            )
        )

    def _post_reset(self, fields: dict[str, str]) -> None:
        token = fields.get("token", "")
        email = _TOKENS.peek(token)
        if email is None:
            self._respond(_forgot(_ERROR.format(_EXPIRED)))
            return
        error = validate_password(fields.get("password", ""), fields.get("confirm", ""))
        if error:
            self._respond(_reset(token, _ERROR.format(error)))
            return
        digest = bcrypt.hashpw(fields["password"].encode(), bcrypt.gensalt())
        try:
            response = _stub().UpdatePassword(
                UpdatePasswordReq(email=email, new_hash=digest)
            )
        except grpc.RpcError:
            self._respond(_reset(token, _ERROR.format(_LATER)), status=503)
            return
        if response.not_found:
            self._respond(_forgot(_ERROR.format(_EXPIRED)))
            return
        _TOKENS.consume(token)
        self._respond(_page("Password changed", "<p>You can sign in now.</p>"))

    def _not_found(self) -> None:
        self.send_response(404)
        self.end_headers()

    def _respond(self, body: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # The reset link carries its token in the URL: never pass it on as a referrer.
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 5559), Handler).serve_forever()
