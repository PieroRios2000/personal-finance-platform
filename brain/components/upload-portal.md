---
type: component
phase: 5
status: built
task: T44, T46, T47, T48
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
| [`ingestion/submissions.py`](../../ingestion/submissions.py) | A request: its folder, manifest, statuses and the emails to the sender (T48, [ADR 0041](../decisions/0041-uploads-are-requests-accepted-or-rejected-whole.md)) |
| [`scripts/process_submissions.py`](../../scripts/process_submissions.py) | `make ingest-uploads`: reads every file of a waiting request, accepts or rejects it whole, runs `pfp ingest` and emails the sender; `make submissions`, `make decide-submission` |
| [`scripts/review_uploads.py`](../../scripts/review_uploads.py) | `make review-uploads`: requests waiting in `review` (another bank, kind or currency), by id, bank, kind, currency, files |
| [`alerting/channels.py`](../../alerting/channels.py) (reused) | The email to the owner when a file is kept for review: bank, kind, currency, counts |
| `make ingest-uploads` | One `pfp ingest` per inbox folder, then `make build` |

## Tests

Static checks in `tests/test_upload_portal.py`, unit tests for `unlock` and the dispatcher hint, and
`tests/test_upload_flow_portal_e2e.py` (`pytest -m portal`, CI's `portal-e2e` job) against the real services.

## Related

[Dex](dex.md), [Inbox organizer](inbox-organizer.md), [Users and accounts](../concepts/users-and-accounts.md).
