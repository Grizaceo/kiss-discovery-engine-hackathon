# KISS Discovery Engine

Created 2026-10-17T16:26:36.417691-03:00. New event implementation informed by preparatory design, not copied from earlier KISS code. Local-only MVP, no payments.

**Mercury generates. Real microVM forks execute. Tests decide.**

## Working MVP

Generate alternative Python algorithms, evaluate each in a real CreateOS fork, select correctness before measured time, and revise the winner from its own code, feedback and paused VM. Logical code lineage and physical fork lineage are separate. Append-only events and standalone reports preserve code, failures, metrics, selection and cleanup.

```sh
uv sync --locked --group dev
uv run pytest -q
uv run ruff check src tests
uv run kiss serve --port 8097
```

Open **http://127.0.0.1:8097**. One bounded real job at a time. Standalone reports: `runs/<run-id>/report.html`.

## Credentials and stack

The authorized Stripe Projects `setup` stack was reused with supported `stripe projects pull --skip-skills --yes`, without duplicate provisioning or plan changes. `.env` and `.projects/` stay ignored. On another machine inspect `stripe projects pull --help` and authorize/select your existing stack.

Provide `CREATEOS_API_KEY` and `MERCURY_API_KEY` through the orchestrator environment or ignored `.env`; aliases are in `.env.example`. Optional `MERCURY_ENV_FILE` points to a separate private dotenv file. On this workstation the existing authorized Mercury file is loaded directly, never copied. Keys never go to guests or frontend. Missing credentials produce a visible error, not a simulation.

## Commands

```sh
uv run kiss smoke
uv run kiss run --rounds 2 --width 2 --max-candidates 3 --max-sandboxes 4 --max-model-calls 5 --search-seconds 300 --benchmark-n 20000
# Smaller initial-candidate -> own-parent-revision chain:
uv run kiss run --rounds 2 --width 1 --max-candidates 2 --max-sandboxes 3 --max-model-calls 5 --search-seconds 240 --benchmark-n 20000
# Hand-authored remote failure fixtures, NOT Mercury output:
uv run kiss failures
# Read-only reconciliation of only this repository's recorded resource IDs:
uv run kiss audit
```

Remote runs consume existing credits. Candidates, creations, rounds, model attempts and wall time are capped. Cleanup has separate finite bounds. Retries for 429, truncation and malformed content count against the same call budget and retain every attempt. No substitute model.

## Exact task

`count_pairs(a: list[int], b: list[int], lower: int, upper: int) -> int` counts cross-list index pairs satisfying inclusive bounds. Duplicates count by index. Empty lists or `lower > upper` yield zero. Inputs must remain unchanged. Values within ±10^9; bounds within ±2×10^9; up to 10^6 items per list; standard library only. Finite demo tests do not prove every permitted input.

## Measurement and safety

60 supervisor-checked tests; limited counterexamples, not the hidden suite, go to Mercury. Root-owned trusted harness and `nobody` worker inside each VM. Generated/fixture solutions are never imported or executed on the host. Worker PID data is never trusted for root process termination.

Expected answers and baseline remain outside candidate Python. Three distinct measured datasets; supervisor wall time minus a same-dataset null roundtrip estimates candidate time. Internal worker times are diagnostic. Subtraction is noisy: `performance_met` is a finite-run threshold, **not statistically established or portable improvement**. The final child was slower; the parent honestly remained best. This is not certification against deliberately hostile Python.

Before checkpointing, evaluation ends, unprivileged activity is killed/checked and transient artifacts removed. No secrets in guests; ingress disabled. Package-host egress passed positive/negative probes, not a universal deny-all audit. UI is loopback-only, validates Host/Origin, escapes model text and never serves arbitrary files.

## Evidence and handoff

See [verification](docs/VERIFICATION.md), [demo](docs/DEMO.md), [decisions](docs/DECISIONS.md), [provenance](docs/PROVENANCE.md) and [state](STATE.md).

Final two-approach chain `search-20261017T215022-01459f`: `g0-c0` (`sorted-bisect`, 60/60, `6.942 ms`) and `g0-c1` (`two-pointer`, 60/60, `9.667 ms`) forked from paused base; `g0-c0` selected as Round 0 parent; child `g1-c0` revised `g0-c0` from its own code/feedback inside a physical fork of `g0-c0`'s paused VM (`60/60`, `6.553 ms`, `4/4` sandboxes destroyed). Earlier chain `search-20261017T200437-128ee8` (`width=1`) shows parent `g0-c0` (`6.515 ms`) remaining ahead of child `g1-c0` (`6.587 ms`), illustrating finite-run timing noise. Run `search-20261017T195122-af1869` preserves a wrong initial solution (`5/60`) and a real revision under the historical worker-timed method. Audit `audit-20261017T215138-6151e4` read back **34/34 owned resources destroyed** (20,350 provider-reported tokens across 16 usage events; credit/currency cost not inferred). Raw evidence is private and ignored.

**No public hosting, push or submission without permission.** Code **CreateOS-2026**. Both destinations: extra Discord deadline link and https://projects.dev/leaderboard. Internal target 21:45 Chile; deadline 22:00. Nothing submitted.
