"""Explicit fixture integration tests. Never attributed to Mercury, never run on host."""

import json

from .harness import build_harness, parse_result
from .runtime import Ledger, Sandboxes, deadline, load_secrets
from .smoke import checked

FIXTURES = [
    ("incorrect", "def count_pairs(a,b,lower,upper):\n    return 0\n", "test_failure"),
    (
        "controlled-timeout",
        "def count_pairs(a,b,lower,upper):\n    while True: pass\n",
        "timeout",
    ),
    ("syntax-error", "def count_pairs(:\n", "compilation_error"),
    (
        "input-mutation",
        "def count_pairs(a,b,lower,upper):\n    a.append(9)\n    return 0\n",
        "test_failure",
    ),
    (
        "timing-spoof",
        "from bisect import bisect_left,bisect_right\nimport time\ntime.perf_counter=lambda:0.0\ndef count_pairs(a,b,lower,upper):\n    if lower>upper: return 0\n    s=sorted(b)\n    return sum(bisect_right(s,upper-x)-bisect_left(s,lower-x) for x in a)\n",
        "protocol_error",
    ),
]


def failures():
    ledger = Ledger("fixtures")
    secrets = load_secrets()
    ledger.secrets = list(secrets.values())
    ledger.event(
        "run_started",
        kind="explicit test fixtures, NOT Mercury output",
        max_sandboxes=6,
    )
    adapter = Sandboxes(secrets["createos"], ledger, max_created=6)
    results = []
    try:
        with deadline(300):
            base = adapter.create()
            checked(
                adapter,
                base,
                "sh",
                [
                    "-c",
                    "mkdir -p /workspace/candidate /workspace/.kiss_trusted; chmod 755 /workspace /workspace/candidate /workspace/.kiss_trusted",
                ],
            )
            adapter.upload(
                base, "/workspace/.kiss_trusted/harness.py", build_harness(1730, 5000)
            )
            adapter.pause(base)
            for name, code, expected in FIXTURES:
                box = adapter.fork(base)
                adapter.upload(box, "/workspace/candidate/solution.py", code)
                checked(
                    adapter, box, "chmod", ["644", "/workspace/candidate/solution.py"]
                )
                out = adapter.exec(
                    box,
                    "timeout",
                    [
                        "-k",
                        "2",
                        "35",
                        "/usr/bin/python3",
                        "/workspace/.kiss_trusted/harness.py",
                    ],
                    timeout=40,
                )
                result = parse_result(out["standard_output"])
                row = {
                    "fixture": name,
                    "expected": expected,
                    "actual": result["status"],
                    "ok": result["status"] == expected,
                    "sandbox_id": box.id,
                    "forked_from": box.data.forked_from,
                    "feedback": result,
                }
                ledger.event("fixture_result", **row)
                ledger.artifact(
                    name + ".json",
                    {
                        "fixture": True,
                        "attribution": "hand-authored failure fixture, not Mercury",
                        "source": code,
                        "execution": out,
                        "result": row,
                    },
                )
                results.append(row)
                adapter.destroy(box)
    except Exception as exc:  # noqa: BLE001 - record failure and always clean owned resources
        ledger.event("run_error", error=str(exc), error_type=type(exc).__name__)
        results.append({"ok": False, "error": str(exc)})
    finally:
        cleanup = adapter.cleanup()
        summary = {
            "run_id": ledger.run_id,
            "kind": "explicit test fixtures, not Mercury",
            "ok": len(results) == len(FIXTURES)
            and all(r["ok"] for r in results)
            and all(r["status"] == "destroyed" for r in cleanup),
            "results": results,
            "cleanup": cleanup,
        }
        ledger.artifact("summary.json", summary)
        print(
            json.dumps(
                {
                    "run_id": ledger.run_id,
                    "path": str(ledger.path),
                    "ok": summary["ok"],
                    "results": [
                        {k: r.get(k) for k in ["fixture", "expected", "actual", "ok"]}
                        for r in results
                    ],
                    "cleanup": cleanup,
                },
                indent=2,
            )
        )
    return summary


if __name__ == "__main__":
    raise SystemExit(0 if failures()["ok"] else 1)
