---
type: component
phase: 5
status: built
task: T44, T46
---

# Upload portal

Signed-in people send their bank statements; each lands, unlocked, in that person's folder
of the inbox for the owner to process. Design in
[ADR 0040](../decisions/0040-upload-portal-unlocks-at-upload-and-owner-processes.md).

## Pieces

| Piece | What it does |
|---|---|
| [`upload/server.py`](../../upload/server.py) | The Flask app: sign-in through [Dex](dex.md) (client `portal`), the upload form, the per-account `user_id` lookup over Dex's gRPC API |
| [`upload/portal.py`](../../upload/portal.py) | Pure logic: `user_id` generation, the banks offered, the per-person upload limit |
| [`ingestion/unlock.py`](../../ingestion/unlock.py) | Unlocks a PDF with the typed password and tags it with the chosen bank; the dispatcher reads the tag as a hint |
| [`bi/docker-compose.yml`](../../bi/docker-compose.yml) | The `upload` service (port 5560 on 127.0.0.1), the inbox mounted read-write |
| [`scripts/review_uploads.py`](../../scripts/review_uploads.py) | `make review-uploads`: files kept in `_new_bank/` (another bank, or a kind no parser reads), counted by bank and kind |
| `make ingest-uploads` | One `pfp ingest` per inbox folder, then `make build` |

## Tests

Static checks in `tests/test_upload_portal.py`, unit tests for `unlock` and the dispatcher hint, and
`tests/test_upload_flow_portal_e2e.py` (`pytest -m portal`, CI's `portal-e2e` job) against the real services.

## Related

[Dex](dex.md), [Inbox organizer](inbox-organizer.md), [Users and accounts](../concepts/users-and-accounts.md).
