# State
Created 2026-10-17T16:26:36.417691-03:00; updated during final verification on 2026-10-17.

## Done
- Empty-directory event implementation; explicit provenance; uv lockfile; existing Stripe Projects stack reused.
- Official SDK adapter, direct Mercury generator, remote harness, bounded search, selection/deduplication, own-parent revisions, separate code/VM lineage, events/report and loopback UI.
- Review fixes verified: untrusted PID ignored; authoritative supervisor timing and separate trusted baseline; finite timing checks; input mutation detection; memory cap; root-only supervisor file.
- Counted bounded retries for 429, truncation and malformed structured responses, all attempts retained.
- 85 offline tests passed. No generated/fixture solution run on host.
- Final independent read-only review: no host-safety or false-success blocker found; hostile-code certification explicitly out of scope.
- Added `docs/CREATEOS_REFERENCE.md`: verified CreateOS ecosystem reference (CLI, agent plugins, six SDKs, quotas, canonical links) carried over from the event preparation workspace; no code change.
- Added `docs/CREATEOS_GUIDE.html`: full CreateOS usage guide (Spanish) built from the official documentation corpus (171 pages; live, self-contained HTML); carried over from the event preparation workspace; no code change.

## Real evidence
- `runs/smoke-20261017T200218-804c8e/summary.json`: inheritance, independence, two running children, pypi.org positive/example.com negative probes; three resources destroyed.
- `runs/fixtures-20261017T195514-b9747e/summary.json`: incorrect, timeout, syntax, mutation and timing-spoof (`time.perf_counter` monkeypatch → `protocol_error`) all classified as expected; six resources destroyed.
- `runs/search-20261017T195122-af1869/`: two approaches + revision; 60/60, 5/60, 60/60. Historical worker-only timings are NOT final authoritative scoring.
- `runs/search-20261017T195854-92454c/`: real browser-launched run; truncated child preserved.
- `runs/search-20261017T200300-4a7d42/`: two correct initial candidates (`g0-c1` `two-pointer` at `5.678 / 6.828 ms = 0.832×`, `agreement: true` → `faster beyond the noise band`), invalid child response preserved honestly.
- `runs/search-20261017T200437-128ee8/`: supervisor-timed 1-width chain; parent/child 60/60, 6.515/6.587 ms (`0.98× baseline · parity`), no improvement claim. Three resources destroyed, two real Mercury calls, stop=max_rounds.
- `runs/search-20261017T215022-01459f/`: final complete bounded demo chain (`rounds=2, width=2, max_candidates=3, max_sandboxes=4, max_model_calls=5, search_seconds=300, benchmark_n=20000`). Base `sb-01m55xge5pz50x960atf55199r` → `g0-c0` (`sorted-bisect`, VM `sb-01m55xgnr1xme51d4bab9bnnvs`, 60/60, `6.942 / 7.133 ms = 0.973×`, `agreement: false` → `parity within measurement noise`) & `g0-c1` (`two-pointer`, VM `sb-01m55xh7htvnf8cgee3gxfwqds`, 60/60, `9.667 / 7.166 ms = 1.349×`, `agreement: true` → `slower`) → `g0-c0` selected after Round 0 → `g1-c0` (`parent-feedback-revision`, VM `sb-01m55xhp139bt4r3m2hjq99ewz` physically forked from `g0-c0`'s paused VM, 60/60, `6.553 / 7.346 ms = 0.892×`, `agreement: false` → `parity within measurement noise`; selected by rule; difference within measurement noise; note: `g0-c0`'s historical `not selected` text in `summary.json` came from pre-fix bug K02 and raw `runs/` was not rewritten; 3 Mercury calls; 4/4 resources destroyed).
- `runs/audit-20261017T215138-6151e4/summary.json` (superseding `audit-20261017T205226-221420`): 34/34 owned resources destroyed, `unresolved: []`. 20,350 provider-reported tokens across 16 usage events (prompt: 11,271; completion: 9,079). Credit/currency consumption not observable, not inferred.
- Chromium DOM and visual screenshots (`runs/captures-20261017/`) verified rendering, live vs historical run state, task contract, dual lineage, timings, errors and selection reasons. Dashboard http://127.0.0.1:8097.

## Closing
Final UX refinements, bounded 2-approach demo run (`search-20261017T215022-01459f`), read-only resource reconciliation (`34/34 destroyed`), presentation/submission materials (`docs/DEMO.md`), offline tests and lint completed. No public exposure, push, submission, plan change or payment. No sandbox active.

## Next (prepared locally; awaiting explicit authorization)
- **Prepared & verified locally (no external side effects performed):**
  - Read-only repo hygiene verified (`.env`, `.projects/`, `runs/` ignored; `git log --all --name-only` clean; `evidence/` scanned against all local secrets and key/path patterns).
  - Exact `gh repo create ... --public --push` and GitHub Pages (`evidence/index.html`) commands documented in `docs/DEMO.md` §4.
  - All `https://projects.dev/leaderboard` form values prepared (`Name`, in-memory `stripe whoami --format json`, `Stack URL` `https://projects.dev/s#v1:createos~project`, code `CreateOS-2026`).
- **Gated on explicit authorization from Cristóbal:**
  1. **Single final live demo run** (`uv run kiss run --rounds 2 --width 2 --max-candidates 3 --max-sandboxes 4 --max-model-calls 5 --search-seconds 300 --benchmark-n 20000`) — wait for Cristóbal's explicit signal after external audit.
  2. **Public GitHub repo creation + `git push`**.
  3. **GitHub Pages activation** serving static `evidence/index.html` as `Deployed Project URL`.
  4. **Submission to `https://projects.dev/leaderboard` and Discord link** (requires 6-digit email OTP at submission time, plus confirmation of 22:00 vs 23:00 Chile deadline).

Last verified: 2026-10-17T20:18:00-03:00. Block 7 / K14: atomic `Ledger.artifact` writes via temporary file + `os.replace`; 85 offline tests passed.
