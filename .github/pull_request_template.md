## What

<!-- What changes and why. Name the task from tasks/todo.md (e.g. T6) and the ADR if a decision was made. -->

## Verification

<!-- Commands you ran and their real output (summarized). "Tests pass" isn't enough. -->

## Notes

<!-- Deviations from the plan, risks, open items, and anything that needs Piero's action. -->

## Definition of Done

<!-- Copied from the Definition of Done in tasks/plan.md: if it changes there, update it here too. -->

- [ ] Task acceptance criteria met (boxes checked in `tasks/todo.md`).
- [ ] `make check-task` green locally and CI's blocking checks green.
- [ ] Behavior verified by running it, not just tests.
- [ ] New tests fail without the change and pass with it.
- [ ] No real data or secrets in the diff.
- [ ] Brain updated: the component or concept note, `brain/phases/phase-1.md`, and an ADR if a decision was made.
- [ ] `SETUP.md` kept current if the task adds libraries, programs, versions or env vars.
- [ ] `ponytail-review` and `review` with no pending findings.
- [ ] PR reviewed and merged by Piero.
