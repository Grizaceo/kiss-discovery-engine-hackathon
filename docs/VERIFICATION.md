# Verification evidence
Created 2026-10-17 during the event. Evidence below is private/local, not public URLs.

| Requirement | Evidence | Result |
|---|---|---|
| Real fork, inheritance, independent modification | `runs/smoke-20261017T200218-804c8e/summary.json` + events | Passed |
| Two children running | same smoke, `two_children_running` | 2 observed, not an account maximum |
| Positive/negative egress | same smoke, `egress_probe` | pypi.org 200; example.com URLError |
| Real direct Mercury and remote code execution | `search-20261017T200437-128ee8` | 2 provider calls, both candidates 60/60 |
| Own-parent feedback and physical chaining | child prompt, summary, fork events in same run | code parent g0-c0; physical origin exactly its VM |
| Distinct initial approaches and selection | `search-20261017T195122-af1869`, `search-20261017T200300-4a7d42` | sorted-bisect/two-pointer, failures retained |
| Incorrect/timeout/syntax/mutation/time-spoof | `fixtures-20261017T195514-b9747e` | 5/5 expected classifications |
| Generation/API errors, retry and configured caps | `uv run pytest -q` | 72 offline tests, explicit fakes |
| UI renders actual results and launches | Dedicated local Chromium DOM/API | Passed; browser-created run 195854 |
| Owned resources terminal | `audit-20261017T205226-221420` | 30/30 read back destroyed |

## Final chain: no artificial improvement

Base `sb-01m55qessrtxsccap1d6j0ntr8` → code parent g0-c0 / VM `sb-01m55qf2t7vbfr2jd2z315mtf8` → child g1-c0 / VM `sb-01m55qffayewm116ph9f2ymhsp`.

Both passed 60/60. Supervisor-adjusted medians: parent 6.514931 ms (baseline 6.660695 ms); child 6.587046 ms (baseline 6.752748 ms). Parent remains best; child is slower in this sample. Three distinct datasets of 20,000 items per list, individual samples retained.

Closely spaced measurements and noisy null-roundtrip subtraction do NOT establish robust improvement. `performance_met` is a finite-run threshold. The auxiliary single-shot root cross-check can disagree (`agreement: false` in this run); it is retained, not hidden. No portable speedup claim.

Historical reports retain their original worker-only method: do not pool their timing values with final supervisor scores. Original failed cleanups are not rewritten; the later read-only audit confirms eventual destruction.

## Limits

Not certified against intentionally hostile arbitrary Python. AST filtering is a task-contract check, not a sandbox. Candidate shares its worker interpreter; trusted supervisor protects expected answers and baseline, but containment is not formal verification. Egress probes are empirical, not universal deny-all proof. Finite tests do not prove every input. Provider token usage was observable; currency/credit deltas were not inferred. Offline fakes never substitute for real integration evidence. No publication, push, payment, plan changes or submission performed.

Independent review: `deleg_a74f905f`, read-only; PID and supervisor/baseline fixes confirmed; original four style errors subsequently fixed, current lint clean. The review explicitly preserves hostile-worker/AST-filter limitations.
