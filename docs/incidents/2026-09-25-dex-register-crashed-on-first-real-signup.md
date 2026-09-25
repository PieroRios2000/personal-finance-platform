# 2026-09-25: dex-register crashed on the owner's first real sign-up attempt

**Status:** resolved · **Severity:** near miss (broken page, no data lost or wrong)

## Summary

The owner rolled T40 (self-service registration) into the real `pfp-poc` stack, filled
in the sign-up form, and got `ERR_EMPTY_RESPONSE` instead of an account. `dex-register`
had crashed mid-request: the `dex` container it talks to was still running the
pre-T40 config (no gRPC listener), because `docker compose up` does not restart a
service just because a bind-mounted file's *contents* changed.

## Impact

No account was created, no data was lost or wrong. The owner's one attempt (a real
email, a real password) never reached Dex's storage -- the crash happened before the
gRPC call could succeed.

## Timeline

| When | What happened |
|---|---|
| ~01:19 UTC | `make up` starts `dex-register` (new) and `superset` (rebuilt); `dex` is left running unchanged, since only its *build*, not its bind-mounted config file, differs from before |
| ~01:20 UTC | Owner opens `http://localhost:5559`, fills the form, submits |
| ~01:20 UTC | Browser shows `ERR_EMPTY_RESPONSE`; owner reports it |
| ~01:21 UTC | `docker logs pfp-poc-dex-register-1` shows an unhandled `grpc._channel._InactiveRpcError: ... Connection refused` from `stub.CreatePassword(...)`, crashing the request thread |
| ~01:21 UTC | `docker logs pfp-poc-dex-1` confirms only `http` and `telemetry` listeners came up -- no `grpc` line: the running container's own `config.yaml` (rendered once, at its last start, well before this deploy) has no `grpc:` block |
| ~01:21 UTC | `docker compose restart dex` fails outright: a stale WSL2 bind-mount path (`OCI runtime create failed: ... no such file or directory`) -- a `restart` reuses the container's existing mount table, which pointed at a bind-mount source that no longer resolves |
| ~01:21 UTC | `docker compose up -d --force-recreate dex` succeeds: recreating re-establishes the bind mount fresh; `dex`'s logs now show the `grpc` listener |
| ~01:24 UTC | A real sign-up through the page, then a cleanup delete over gRPC, both succeed |

## Root cause

Two independent causes had to line up:

1. **Compose's own behavior.** `dex`'s service definition (image, environment, the
   *volume mount line itself*) did not change between the T39 and T40 deploys, only the
   *content* of the file that line mounts (`dex/config.yaml.tpl`, which gained a `grpc:`
   block in T40). Compose recreates a container when its service definition changes; a
   bind-mounted file's content is invisible to that comparison. `dex` kept running with
   whatever it had rendered at its *last* start -- no `grpc:` block -- so
   `dex-register`'s very first gRPC call failed with a plain connection refusal.
2. **This project's own gap, found because of (1).** `dex-register/app.py` had no
   handling around the `CreatePassword` call: any `grpc.RpcError` -- unreachable,
   restarting, anything -- propagated out of `do_POST` uncaught, crashing the request
   mid-response. That is what turned "Dex isn't listening yet" into `ERR_EMPTY_RESPONSE`
   and a traceback in the logs, instead of a page saying try again.

## Recovery

1. `docker logs pfp-poc-dex-register-1` and `pfp-poc-dex-1` located both causes.
2. `docker compose -p pfp-poc --profile bi up -d --force-recreate --wait dex` (a plain
   `restart` failed on the stale bind mount) brought `dex` up with the gRPC listener.
3. A real sign-up through the page, verified end to end (a Superset login would have
   worked the same way the T40 PR's own verification showed).
4. The test account was deleted immediately after, over the same gRPC API (a throwaway
   `DeletePassword` client, run once, never committed).
5. `dex-register/app.py` fixed to catch `grpc.RpcError` around the one call that can
   raise it and answer `503` instead of crashing (`fix/dex-register-grpc-error-handling`),
   with a regression test and a live re-check (Dex pointed at an unreachable address)
   that the page answers cleanly instead of crashing.

## What went well / what went wrong

**Well:** the failure was contained to one page, showed up immediately (the owner's
very first click), and both logs pointed straight at the actual causes -- no
speculative debugging needed. The test account never touched real financial data and
was removable the same way it was created.

**Wrong:** T40's own live verification (throwaway `pfp-test-dexreg`, always built fresh
from a clean `make up`) never exercised the specific sequence that broke on the real
stack -- a service whose *config file content* changed but whose *service definition*
did not, on top of an already-running container. A fresh-every-time throwaway project
can't surface that class of bug by construction.

## Prevention

| Action | Where | Status |
|---|---|---|
| Catch `grpc.RpcError` around `CreatePassword`, answer 503 instead of crashing | `dex-register/app.py` | Done (this incident's fix) |
| Note in the rollout step of any future Dex config change: `dex` (and anything else with a bind-mounted config) needs an explicit `--force-recreate`, not just `make up`, when only the *mounted file's content* changed | `docs/operations-log.md` entries going forward | Done (this entry) |

## Lessons

A bind-mounted config file is invisible to Compose's own change detection -- rendered
once, at container start, and never revisited until something *else* about the service
changes. Rolling out a change to one of these files on an already-running stack needs an
explicit recreate, not just `make up`. Separately: any network call from a small,
long-lived server should assume the other side can be briefly unreachable and answer
something, rather than let the exception decide what the client sees.
