# Verification evidence
Created 2026-10-17 during the event. Evidence below is private/local, not public URLs.

| Requirement | Evidence | Result |
|---|---|---|
| Real fork, inheritance, independent modification | `runs/smoke-20261017T200218-804c8e/summary.json` + events | Passed |
| Two children running | same smoke, `two_children_running` | 2 observed, not an account maximum |
| Positive/negative egress | same smoke, `egress_probe` | pypi.org 200; example.com URLError |
| Real direct Mercury and remote code execution | `search-20261017T215022-01459f`, `search-20261017T200437-128ee8` | 3 + 2 provider calls, all passing candidates 60/60 |
| Own-parent feedback and physical chaining | child prompt, summary, fork events in `search-20261017T215022-01459f` & `search-20261017T200437-128ee8` | code parent g0-c0; physical origin exactly its paused VM |
| Distinct initial approaches and selection | `search-20261017T215022-01459f`, `search-20261017T195122-af1869`, `search-20261017T200300-4a7d42` | sorted-bisect/two-pointer, failures retained |
| Incorrect/timeout/syntax/mutation/time-spoof | `fixtures-20261017T195514-b9747e` | 5/5 expected classifications (`timing-spoof` monkeypatches `time.perf_counter` → `protocol_error`) |
| Generation/API errors, retry and configured caps | `uv run pytest -q` | 91 offline tests, explicit fakes |
| UI renders actual results and launches | Dedicated local Chromium DOM/API + visual screenshots | Passed; browser-created run 195854; updated UX verified |
| Owned resources terminal | `audit-20261017T215138-6151e4` | 34/34 read back destroyed |

## Final chains: complete 2-approach demo run and no artificial improvement claims

### 1. Full 2-approach + selection + own-parent revision chain (`search-20261017T215022-01459f`)
Base `sb-01m55xge5pz50x960atf55199r` (paused) →
- Initial candidate `g0-c0` (`sorted-bisect`) / VM `sb-01m55xgnr1xme51d4bab9bnnvs` (forked from base): `60/60`, supervisor-adjusted median `6.941601 ms` vs baseline `7.133359 ms` (`0.973×`, `agreement: false` → `0.97× baseline · parity within measurement noise`).
- Initial candidate `g0-c1` (`two-pointer`) / VM `sb-01m55xh7htvnf8cgee3gxfwqds` (forked from base): `60/60`, supervisor-adjusted median `9.666881 ms` vs baseline `7.165880 ms` (`1.349×`, `agreement: true` → `1.35× baseline · slower`).
- Round 0 selection chose `g0-c0` (`6.942 ms` vs `9.667 ms`) and destroyed `g0-c1`'s VM before Round 1.
- Revision child `g1-c0` (`parent-feedback-revision`) / VM `sb-01m55xhp139bt4r3m2hjq99ewz` (physically forked from `g0-c0`'s paused VM `sb-01m55xgnr1xme51d4bab9bnnvs`, prompted only with `g0-c0` code + feedback): `60/60`, supervisor-adjusted median `6.553484 ms` vs baseline `7.346338 ms` (`0.892×`, `agreement: false` → `0.89× baseline · parity within measurement noise`).
- `g1-c0` was selected by rule; difference within measurement noise (`0.892×` vs `0.973×` of parent `g0-c0`, with single-shot root cross-check `agreement: false`); 3 Mercury calls; 4/4 sandboxes verified destroyed.
- **Historical K02 note (append-only evidence preserved):** In `runs/search-20261017T215022-01459f/summary.json`, `g0-c0`'s final `selection_reason` reads `not selected: ... best=g1-c0` because of bug K02 (when `g1-c0` superseded `g0-c0` in Round 1, `engine.py` cleared `g0-c0`'s `selection_reason` to `None` and the `finally` block wrote `not selected`, even though `events.jsonl` at `21:51:00` and `g1-c0`'s `parent_candidate_id` / `forked_from` record `g0-c0` as the Round 0 winner and parent). K02 is now fixed in code (`selected_in_rounds` + `candidate_superseded`), and the original files in `runs/` were not rewritten.

### 2. Earlier 1-width supervisor-timed chain (`search-20261017T200437-128ee8`)
Base `sb-01m55qessrtxsccap1d6j0ntr8` → code parent g0-c0 / VM `sb-01m55qf2t7vbfr2jd2z315mtf8` → child g1-c0 / VM `sb-01m55qffayewm116ph9f2ymhsp`.

Both passed 60/60. Supervisor-adjusted medians: parent 6.514931 ms (baseline 6.660695 ms); child 6.587046 ms (baseline 6.752748 ms). Parent remains best; child is slower in this sample. Three distinct datasets of 20,000 items per list, individual samples retained.

Closely spaced measurements and noisy null-roundtrip subtraction do NOT establish robust improvement in either `search-20261017T215022-01459f` or `search-20261017T200437-128ee8`. `performance_met` is a finite-run threshold. The auxiliary single-shot root cross-check can disagree (`agreement: false` retained in both runs); it is never hidden. No portable speedup claim.

Historical reports retain their original worker-only method: do not pool their timing values with final supervisor scores. Original failed cleanups are not rewritten; the later read-only audit confirms eventual destruction.

## Limits

Not certified against intentionally hostile arbitrary Python. AST filtering is a task-contract check, not a sandbox. Candidate shares its worker interpreter; trusted supervisor protects expected answers and baseline, but containment is not formal verification. Egress probes are empirical, not universal deny-all proof. Finite tests do not prove every input. Provider token usage was observable; currency/credit deltas were not inferred. Offline fakes never substitute for real integration evidence. No publication, push, payment, plan changes or submission performed.

Independent review: `deleg_a74f905f`, read-only; PID and supervisor/baseline fixes confirmed; original four style errors subsequently fixed, current lint clean. The review explicitly preserves hostile-worker/AST-filter limitations.

Final closeout also verified a clean checkout with `uv sync --locked --group dev`, offline tests, lint and CLI help. Every new candidate now receives an explicit selection/non-selection reason (including duplicates and generation failures); historical evidence is not rewritten.
