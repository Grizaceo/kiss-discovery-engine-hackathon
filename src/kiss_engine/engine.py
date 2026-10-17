"""Bounded, correctness-first search with real physical VM ancestry."""

from __future__ import annotations

import hashlib
import json
import math
import signal
import time
from dataclasses import asdict, dataclass

from .harness import build_harness, parse_result
from .mercury import APPROACHES, TASK, GenerationError, Mercury
from .runtime import Ledger, Sandboxes, deadline, load_secrets, projection
from .smoke import checked


@dataclass
class Limits:
    rounds: int = 2
    width: int = 2
    max_candidates: int = 3
    max_model_calls: int = 5
    max_sandboxes: int = 4
    search_seconds: int = 360
    benchmark_n: int = 20000
    seed: int = 1729
    stop_on_target: bool = False

    def validate(self):
        bounds = {
            "rounds": (1, 3),
            "width": (1, 2),
            "max_candidates": (1, 5),
            "max_model_calls": (1, 8),
            "max_sandboxes": (2, 6),
            "search_seconds": (30, 600),
            "benchmark_n": (1000, 100000),
            "seed": (0, 2**31 - 1),
        }
        for name, (lo, hi) in bounds.items():
            value = getattr(self, name)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"{name} must be an integer in [{lo},{hi}]")


def rank(candidate):
    f = candidate.get("feedback", {})
    correct = f.get("status") in {"correct", "performance_met"}
    ms = f.get("candidate_ms")
    ms = (
        ms
        if isinstance(ms, (int, float)) and math.isfinite(ms) and ms >= 0
        else float("inf")
    )
    return (not correct, -f.get("tests_passed", 0), ms, candidate["candidate_id"])


def feedback_for_model(result):
    return {
        k: result.get(k)
        for k in (
            "status",
            "tests_passed",
            "total",
            "errors",
            "candidate_ms",
            "baseline_ms",
            "speedup",
            "detail",
            "benchmark",
        )
    }


def run_search(limits=None):
    limits = limits or Limits()
    limits.validate()
    ledger = Ledger("search")
    secrets = load_secrets()
    ledger.secrets = list(secrets.values())
    config = asdict(limits)
    ledger.artifact("config.json", config)
    ledger.event(
        "run_started",
        config=config,
        task=TASK,
        provider="Inception direct",
        model="mercury-2.5",
        selection_rule="correctness first, then tests_passed, then median supervisor-measured milliseconds; trusted reference runs outside candidate; not adversarial benchmark certification",
        stop_policy="fixed bounded exploration unless stop_on_target=true",
        cost="unknown unless returned by provider",
    )
    summary = {
        "run_id": ledger.run_id,
        "started_at": None,
        "status": "running",
        "config": config,
        "candidates": [],
        "best_candidate_id": None,
        "stop_reason": None,
        "resources": [],
        "warnings": [],
    }
    summary["started_at"] = ledger.event("search_preparing")["timestamp"]
    ledger.artifact("summary.json", summary)
    adapter = None
    mercury = None
    seen = {}
    candidate_boxes = {}

    def cancelled(*_):
        raise KeyboardInterrupt("Search cancelled; cleaning owned resources")

    old_term = signal.signal(signal.SIGTERM, cancelled)
    try:
        with deadline(limits.search_seconds):
            adapter = Sandboxes(
                secrets["createos"], ledger, max_created=limits.max_sandboxes
            )
            mercury = Mercury(
                secrets["mercury"], ledger, max_calls=limits.max_model_calls
            )
            base = adapter.create()
            checked(
                adapter,
                base,
                "sh",
                [
                    "-c",
                    "mkdir -p /workspace/candidate /workspace/.kiss_trusted; chmod 755 /workspace /workspace/candidate /workspace/.kiss_trusted; id -u; python3 --version; command -v runuser",
                ],
            )
            harness = build_harness(limits.seed, limits.benchmark_n)
            adapter.upload(base, "/workspace/.kiss_trusted/harness.py", harness)
            checked(
                adapter,
                base,
                "sh",
                [
                    "-c",
                    "chmod 444 /workspace/.kiss_trusted/harness.py; printf kiss-base > /workspace/base-marker; /usr/bin/python3 -m py_compile /workspace/.kiss_trusted/harness.py",
                ],
            )
            ledger.event(
                "base_ready",
                sandbox_id=base.id,
                harness_sha256=hashlib.sha256(harness.encode()).hexdigest(),
                secrets_in_guest=False,
            )
            adapter.pause(base)
            parent = None
            stop = False
            for generation in range(limits.rounds):
                count = limits.width if generation == 0 else 1
                round_candidates = []
                for index in range(count):
                    if len(summary["candidates"]) >= limits.max_candidates:
                        summary["stop_reason"] = "max_candidates"
                        stop = True
                        break
                    if mercury.calls >= limits.max_model_calls:
                        summary["stop_reason"] = "max_model_calls"
                        stop = True
                        break
                    if adapter.attempts >= limits.max_sandboxes:
                        summary["stop_reason"] = "max_sandboxes"
                        stop = True
                        break
                    cid = f"g{generation}-c{index}"
                    approach = (
                        APPROACHES[index % len(APPROACHES)][0]
                        if generation == 0
                        else "parent-feedback-revision"
                    )
                    c = {
                        "candidate_id": cid,
                        "parent_candidate_id": parent["candidate_id"]
                        if parent
                        else None,
                        "generation": generation,
                        "requested_approach": approach,
                        "sandbox_id": None,
                        "forked_from": None,
                        "status": "generating",
                        "selection_reason": None,
                    }
                    summary["candidates"].append(c)
                    ledger.event("candidate_started", **c)
                    try:
                        generated = mercury.generate(
                            cid,
                            approach,
                            parent={
                                "code": parent["code"],
                                "feedback": feedback_for_model(parent["feedback"]),
                            }
                            if parent
                            else None,
                        )
                        c.update(generated)
                        sha = c["code_sha256"]
                        if sha in seen:
                            c.update(
                                status="duplicate",
                                duplicate_of=seen[sha],
                                feedback={
                                    "status": "duplicate",
                                    "tests_passed": 0,
                                    "total": 60,
                                },
                                selection_reason="identical source hash; not re-evaluated",
                            )
                            ledger.event(
                                "candidate_duplicate",
                                candidate_id=cid,
                                duplicate_of=seen[sha],
                            )
                            continue
                        seen[sha] = cid
                        physical_parent = (
                            candidate_boxes[parent["candidate_id"]] if parent else base
                        )
                        box = adapter.fork(physical_parent)
                        candidate_boxes[cid] = box
                        c.update(
                            sandbox_id=box.id,
                            forked_from=projection(box).get("forked_from"),
                            status="evaluating",
                        )
                        ledger.event(
                            "candidate_evaluating",
                            candidate_id=cid,
                            parent_candidate_id=c["parent_candidate_id"],
                            sandbox_id=box.id,
                            forked_from=c["forked_from"],
                        )
                        adapter.upload(
                            box, "/workspace/candidate/solution.py", c["code"]
                        )
                        checked(
                            adapter,
                            box,
                            "sh",
                            [
                                "-c",
                                "chmod 644 /workspace/candidate/solution.py; rm -rf /workspace/candidate/__pycache__; chmod 755 /workspace/candidate",
                            ],
                        )
                        started = time.monotonic()
                        output = adapter.exec(
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
                        c["evaluation_wall_ms"] = (time.monotonic() - started) * 1000
                        c["execution"] = output
                        try:
                            verdict = parse_result(output.get("standard_output", ""))
                            expected_exit = (
                                0
                                if verdict["status"] in {"correct", "performance_met"}
                                else 2
                                if verdict["status"] == "harness_error"
                                else 10
                            )
                            if output.get("exit_code") != expected_exit:
                                raise ValueError(
                                    "Harness verdict and exit status disagree"
                                )
                        except (ValueError, TypeError) as exc:
                            verdict = {
                                "status": "timeout"
                                if output.get("exit_code") in {124, 137}
                                else "protocol_error",
                                "tests_passed": 0,
                                "total": 60,
                                "detail": str(exc),
                                "errors": [],
                            }
                        c.update(feedback=verdict, status=verdict["status"])
                        ledger.artifact(
                            f"candidates/{cid}/evaluation.json",
                            {"execution": output, "feedback": verdict},
                        )
                        ledger.event(
                            "candidate_result",
                            candidate_id=cid,
                            status=c["status"],
                            feedback=verdict,
                            evaluation_wall_ms=c["evaluation_wall_ms"],
                        )
                        # Stop all unprivileged activity before checkpointing; no running benchmarks inherited.
                        checked(
                            adapter,
                            box,
                            "sh",
                            [
                                "-c",
                                "pkill -KILL -u nobody 2>/dev/null || true; rm -rf /workspace/candidate/__pycache__; if pgrep -u nobody >/dev/null; then exit 1; fi",
                            ],
                        )
                        adapter.pause(box)
                        round_candidates.append(c)
                    except GenerationError as exc:
                        c.update(
                            status=exc.status,
                            feedback={
                                "status": exc.status,
                                "tests_passed": 0,
                                "total": 60,
                                "detail": str(exc),
                                "errors": [],
                            },
                        )
                        ledger.event(
                            "candidate_generation_failed",
                            candidate_id=cid,
                            status=exc.status,
                            error=str(exc),
                        )
                    ledger.artifact("summary.json", summary)
                selectable = [
                    c
                    for c in summary["candidates"]
                    if c["candidate_id"] in candidate_boxes
                    and c.get("feedback", {}).get("status")
                    not in {"harness_error", "protocol_error", "infrastructure_error"}
                ]
                if not selectable:
                    summary["stop_reason"] = (
                        summary["stop_reason"] or "no_evaluable_candidates"
                    )
                    break
                winner = min(selectable, key=rank)
                previous = parent
                parent = winner
                summary["best_candidate_id"] = winner["candidate_id"]
                for cand in selectable:
                    if cand["candidate_id"] != winner["candidate_id"]:
                        cand["selection_reason"] = None
                winner["selection_reason"] = (
                    "correctness/test count first; fastest supervisor-measured median among tied passing candidates; noisy finite-run estimate"
                )
                ledger.event(
                    "selection",
                    candidate_id=winner["candidate_id"],
                    previous_candidate_id=previous["candidate_id"]
                    if previous
                    else None,
                    reason=winner["selection_reason"],
                )
                # Keep only reusable checkpoint plus base; destroy discarded children before next generation.
                for old_id, box in list(candidate_boxes.items()):
                    if old_id != winner["candidate_id"]:
                        adapter.destroy(box)
                        del candidate_boxes[old_id]
                if (
                    limits.stop_on_target
                    and winner.get("feedback", {}).get("status") == "performance_met"
                ):
                    summary["stop_reason"] = "performance_target_met"
                    break
                if stop:
                    break
            summary["stop_reason"] = summary["stop_reason"] or "max_rounds"
            summary["status"] = (
                "completed" if summary["best_candidate_id"] else "failed"
            )
    except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001 - preserve failure evidence and run cleanup
        summary.update(
            status="failed",
            stop_reason="cancelled"
            if isinstance(exc, KeyboardInterrupt)
            else "time_limit"
            if isinstance(exc, TimeoutError)
            else "infrastructure_error",
            error=str(exc),
        )
        ledger.event("run_error", error_type=type(exc).__name__, error=str(exc))
    finally:
        signal.signal(signal.SIGTERM, old_term)
        if mercury:
            summary["model_calls"] = mercury.calls
            mercury.close()
        if adapter:
            summary["resources"] = adapter.cleanup()
            if any(r["status"] != "destroyed" for r in summary["resources"]):
                summary["warnings"].append(
                    "Some cleanup states unresolved; exact owned IDs and errors in cleanup.json"
                )
        for candidate in summary["candidates"]:
            if not candidate.get("selection_reason"):
                f = candidate.get("feedback") or {}
                passed = f.get("tests_passed", 0)
                total = f.get("total", 60)
                ms = f.get("candidate_ms")
                ms_note = (
                    f", median={ms:.3f}ms"
                    if isinstance(ms, (int, float)) and math.isfinite(ms)
                    else ""
                )
                candidate["selection_reason"] = (
                    f"not selected: status={candidate['status']} ({passed}/{total} tests{ms_note}); "
                    f"best={summary['best_candidate_id']}; correctness before measured speed"
                )
                ledger.event(
                    "candidate_selection_outcome",
                    candidate_id=candidate["candidate_id"],
                    reason=candidate["selection_reason"],
                )
        summary["finished_at"] = ledger.event(
            "run_finished", status=summary["status"], stop_reason=summary["stop_reason"]
        )["timestamp"]
        ledger.artifact("summary.json", summary)
        from .report import render_report

        ledger.artifact("report.html", render_report(ledger.clean(summary)))
        print(
            json.dumps(
                {
                    "run_id": ledger.run_id,
                    "path": str(ledger.path),
                    "status": summary["status"],
                    "best": summary["best_candidate_id"],
                    "stop": summary["stop_reason"],
                    "warnings": summary["warnings"],
                }
            )
        )
    return summary
