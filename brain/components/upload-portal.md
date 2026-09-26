---
type: component
phase: 5
status: built
task: T44
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
| `make ingest-uploads` | One `pfp ingest` per inbox folder, then `make build` |

## Related

[Dex](dex.md), [Inbox organizer](inbox-organizer.md), [Users and accounts](../concepts/users-and-accounts.md).
