"""Upload portal (T44, ADR 0040): a signed-in person sends their bank statements and
they land, unlocked, in `inbox/<their user_id>/` for the owner to run `pfp ingest` on.

Signs in through Dex like Superset does (its own OIDC client, `portal`). The
destination never comes from the form: it is the `user_id` of the signed-in account,
looked up in Dex on every request. An account nobody scoped yet (username = its email,
ADR 0036) is given a fresh one the first time, over the same gRPC API `dex-register`
uses. The PDF password is typed per upload, used once to unlock the file
(`ingestion.unlock`) and never stored or logged. `api_pb2*` are generated from
`dex-register/api.proto` at image build time.
"""

import hmac
import os
import secrets
import threading
from pathlib import Path

import grpc
import pikepdf
import portal
from api_pb2 import ListPasswordReq, UpdatePasswordReq
from api_pb2_grpc import DexStub
from authlib.integrations.flask_client import OAuth
from flask import Flask, redirect, render_template_string, request, session, url_for
from werkzeug.wrappers import Response

from ingestion.unlock import unlock

_INBOX_ROOT = Path(os.environ.get("PFP_INBOX_ROOT", "/inbox"))
_GRPC_ADDR = os.environ.get("PFP_DEX_GRPC_ADDR", "dex:5557")
_DASHBOARD = os.environ.get("PFP_BI_PUBLIC_URL", "")
_LIMIT = portal.UploadLimit()
_RESOLVE_LOCK = threading.Lock()

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ["PFP_UPLOAD_SECRET_KEY"],
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("PFP_UPLOAD_PUBLIC_URL", "").startswith(
        "https://"
    ),
    MAX_CONTENT_LENGTH=portal.MAX_FILE_BYTES * 4,
)

oauth = OAuth(app)
oauth.register(
    "dex",
    client_id="portal",  # public, matches dex/config.yaml.tpl
    client_secret=os.environ["PFP_UPLOAD_OAUTH_CLIENT_SECRET"],
    client_kwargs={"scope": "openid email profile"},
    # Backend calls go to Dex's internal address; the browser is sent to the published
    # one (DEX_ISSUER), the same split as Superset's (bi/superset_config.py).
    server_metadata_url="http://dex:5556/dex/.well-known/openid-configuration",
    authorize_url=f"{os.environ['DEX_ISSUER']}/auth",
)

_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Upload statements</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body { font-family: sans-serif; max-width: 34rem; margin: 3rem auto;
    padding: 0 1rem; }
  label { display: block; margin-top: 1rem; }
  input, select { width: 100%; padding: 0.4rem; box-sizing: border-box; }
  button { margin-top: 1.5rem; padding: 0.5rem 1.5rem; }
  .notice { background: #f3f4f6; padding: 0.75rem 1rem; border-radius: 4px; }
  .error { color: #b91c1c; } .ok { color: #166534; }
</style></head><body>
<h1>Upload statements</h1>
<p>Signed in as {{ email }}. <a href="{{ url_for('logout') }}">Sign out</a>
{% if dashboard %} &middot;
  <a href="{{ dashboard }}">Open the dashboard</a>{% endif %}</p>
<p class="notice">Your files are stored on the machine of whoever runs this
platform, in a folder that is yours, and that person can open them. The password you
type is used once to unlock the file and is never saved.</p>
{% for ok, text in results %}
<p class="{{ 'ok' if ok else 'error' }}">{{ text }}</p>{% endfor %}
{% if message %}<p class="error">{{ message }}</p>{% endif %}
<h2>Bank statements (PDF)</h2>
<form method="post" action="{{ url_for('upload') }}" enctype="multipart/form-data">
  <input type="hidden" name="csrf" value="{{ csrf }}">
  <label>What is it <select name="kind">
    {% for key, label in kinds.items() %}<option value="{{ key }}">{{ label }}</option>
    {% endfor %}</select></label>
  <label>Bank <select name="bank">
    {% for bank in banks %}<option>{{ bank }}</option>{% endfor %}
    <option>{{ other }}</option></select></label>
  <label>If it is another bank, its name
    <input type="text" name="other_bank" maxlength="40" autocomplete="off"></label>
  <label>Currency <select name="currency">
    {% for key, label in currencies.items() %}
    <option value="{{ key }}">{{ label }}</option>{% endfor %}</select></label>
  <label>If it is another currency, its name or code
    <input type="text" name="other_currency" maxlength="20" autocomplete="off"></label>
  <p class="notice">Only some are read today (BCP accounts; Scotiabank cards and
  accounts; soles and dollars). Anything else is kept safely, and the owner first
  reviews how to read it.</p>
  <label>PDF password (leave empty if the file has none)
    <input type="password" name="password" autocomplete="off"></label>
  <label>Files <input type="file" name="files" accept="application/pdf" multiple
    required></label>
  <button type="submit">Upload</button>
</form>
</body></html>
"""


def _stub() -> DexStub:
    return DexStub(grpc.insecure_channel(_GRPC_ADDR))


def _user_id(email: str) -> str | None:
    """The folder and dashboard filter of this account, or None if it has none."""
    with _RESOLVE_LOCK:
        accounts = _stub().ListPasswords(ListPasswordReq()).passwords
        mine = next((a for a in accounts if a.email.lower() == email), None)
        if mine is None:
            return None
        if not portal.is_unscoped(mine.username):
            return mine.username if portal.is_user_id(mine.username) else None
        fresh = portal.new_user_id(email, {a.username for a in accounts})
        response = _stub().UpdatePassword(
            UpdatePasswordReq(email=mine.email, new_username=fresh)
        )
        return None if response.not_found else fresh


def _render(results: list[tuple[bool, str]] | None = None, message: str = "") -> str:
    session.setdefault("csrf", secrets.token_hex(16))
    page: str = render_template_string(
        _PAGE,
        email=session["email"],
        csrf=session["csrf"],
        banks=portal.BANKS,
        other=portal.OTHER_BANK,
        kinds=portal.KINDS,
        currencies=portal.CURRENCIES,
        results=results or [],
        message=message,
        dashboard=_DASHBOARD,
    )
    return page


def _store(user_id: str, content: bytes, *, review: str = "") -> None:
    """In the person's inbox folder, where `pfp ingest` looks; or, for a file no parser
    reads yet, in `_new_bank/` beneath it, which nothing reads."""
    folder = _INBOX_ROOT / user_id / (portal.REVIEW_FOLDER if review else "")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = folder / f"{secrets.token_hex(8)}.pdf"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)


def health() -> str:
    return "ok"


def index() -> Response | str:
    if "email" not in session:
        return redirect(url_for("login"))
    return _render()


def login() -> Response:
    response: Response = oauth.dex.authorize_redirect(
        url_for("callback", _external=True)
    )
    return response


def callback() -> Response:
    token = oauth.dex.authorize_access_token()
    session["email"] = str(token["userinfo"]["email"]).lower()
    return redirect(url_for("index"))


def logout() -> Response:
    session.clear()
    return redirect(url_for("index"))


def upload() -> Response | str:
    if "email" not in session:
        return redirect(url_for("login"))
    if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "-")):
        return _render(message="The form expired. Try again.")
    where = portal.route(
        request.form.get("bank", ""),
        request.form.get("kind", ""),
        request.form.get("other_bank", ""),
        request.form.get("currency", ""),
        request.form.get("other_currency", ""),
    )
    files = [f for f in request.files.getlist("files") if f.filename]
    if where is None or not files:
        return _render(
            message="Choose the kind of file, the bank and the currency (name them "
            "if they are another one) and at least one PDF."
        )
    supported, bank, currency = where
    kind = request.form["kind"]
    if len(files) > portal.MAX_FILES_PER_UPLOAD:
        return _render(
            message=f"At most {portal.MAX_FILES_PER_UPLOAD} files at a time."
        )
    if not _LIMIT.allow(session["email"], len(files)):
        return _render(message="Too many uploads this hour. Try later.")
    try:
        user_id = _user_id(session["email"])
    except grpc.RpcError:
        return _render(message="Try again in a moment.")
    if user_id is None:
        return _render(message="This account cannot upload files. Ask the owner.")

    password = request.form.get("password", "")
    results: list[tuple[bool, str]] = []
    for file in files:
        name = file.filename or "file"
        content = file.read(portal.MAX_FILE_BYTES + 1)
        if len(content) > portal.MAX_FILE_BYTES:
            results.append((False, f"{name}: larger than 15 MB."))
            continue
        try:
            _store(
                user_id,
                unlock(
                    content,
                    password=password,
                    bank=bank,
                    kind=kind,
                    currency=currency,
                ),
                review="" if supported else bank,
            )
        except pikepdf.PasswordError:
            results.append((False, f"{name}: wrong password."))
        except pikepdf.PdfError:
            results.append((False, f"{name}: not a readable PDF."))
        else:
            results.append(
                (True, f"{name}: saved.")
                if supported
                else (
                    True,
                    f"{name}: saved for review. {bank} "
                    f"({portal.KINDS[kind].lower()}, {currency}) "
                    "is not read yet: the owner will look at how to read it, and it "
                    "will not show on your dashboard until then.",
                )
            )
    return _render(results=results)


# Not decorators: Flask is not a dependency of the main project (it runs only in this
# container), so mypy sees its `app` as untyped and would reject an untyped decorator.
app.add_url_rule("/health", view_func=health)
app.add_url_rule("/", view_func=index)
app.add_url_rule("/login", view_func=login)
app.add_url_rule("/callback", view_func=callback)
app.add_url_rule("/logout", view_func=logout)
app.add_url_rule("/upload", view_func=upload, methods=["POST"])
