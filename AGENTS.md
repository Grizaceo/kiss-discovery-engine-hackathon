# Project operating contract
Created 2026-10-17T16:26:36.417691-03:00.

- Work only in this new repository; do not open old KISS implementation repos.
- No generated solution may execute or import on the host. AST validation is allowed.
- Secrets stay in the orchestrator; load private Mercury file in-process, never print.
- Real pause -> paused -> fork; distinguish logical and physical ancestry.
- Bound HTTP calls, waits, candidates, output and resource creation. Reconcile ambiguous writes.
- Cleanup only explicit owned resource IDs. Read back after mutations.
- No public ingress, publishing, push, paid plan, payment or third-party mutation outside project scope.
- Tests decide correctness; preserve failures, regressions, real usage and warnings.
- Offline fakes are tests, never integration evidence.
- Update STATE.md after each block; coherent local commits only.
