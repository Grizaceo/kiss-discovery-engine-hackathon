"""Dashboard checks: real headless Chromium against an offline fixture server.

Fixtures are display-only JSON in a temp dir (never runs/); Popen is faked, so no real run starts.
"""

import json
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from kiss_engine import web
from kiss_engine.web import make_handler

REPO = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
CHROME = next(
    filter(
        None,
        map(
            shutil.which,
            ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"),
        ),
    ),
    None,
)
COMPLETED = "search-20990101T000000-aaaaaa"
LIVE = "search-20990101T000100-bbbbbb"
EVIDENCE = (
    "smoke-20261017T200218-804c8e",
    "fixtures-20261017T195514-b9747e",
    "audit-20261017T215138-6151e4",
)


def _node_has_websocket():
    if not NODE:
        return False
    probe = [NODE, "-e", "process.exit(typeof WebSocket === 'function' ? 0 : 1)"]
    return (
        subprocess.run(probe, check=False, capture_output=True, timeout=20).returncode
        == 0
    )


def _code(marker):
    lines = "".join(f"    # {marker} line {i}: display-only text\n" for i in range(40))
    return f"def count_pairs(a, b, lower, upper):\n{lines}    return 0\n"


def _cand(cid, parent, approach, status, ms, base, agree, reason, sb, fork, gen=0):
    return {
        "candidate_id": cid,
        "parent_candidate_id": parent,
        "generation": gen,
        "requested_approach": approach,
        "approach": approach,
        "status": status,
        "sandbox_id": sb,
        "forked_from": fork,
        "code": _code(f"MARKER-{cid}"),
        "explanation": f"fixture explanation for {cid}",
        "selection_reason": reason,
        "feedback": {
            "status": status,
            "tests_passed": 60,
            "total": 60,
            "candidate_ms": ms,
            "baseline_ms": base,
            "benchmark": {"timed_where": "supervisor wall-clock", "agreement": agree},
        },
    }


def _write_fixture_root(root):
    now = datetime.now(UTC).isoformat()
    completed = {
        "run_id": COMPLETED,
        "status": "completed",
        "stop_reason": "max_rounds",
        "started_at": now,
        "finished_at": now,
        "model_calls": 3,
        "best_candidate_id": "g1-c0",
        "warnings": [],
        "config": {"rounds": 2, "width": 2, "max_candidates": 3},
        "resources": [
            {"id": f"sb-fixture-{x}", "status": "destroyed"}
            for x in ("base", "g0c0", "g0c1", "g1c0")
        ],
        "candidates": [
            _cand(
                "g0-c0",
                None,
                "sorted-bisect",
                "performance_met",
                6.942,
                7.133,
                False,
                "not selected: status=performance_met (60/60 tests, median=6.942ms); best=g1-c0; correctness before measured speed",
                "sb-fixture-g0c0",
                "sb-fixture-base",
            ),
            _cand(
                "g0-c1",
                None,
                "two-pointer",
                "correct",
                9.667,
                7.166,
                True,
                "not selected: status=correct (60/60 tests, median=9.667ms); best=g1-c0; correctness before measured speed",
                "sb-fixture-g0c1",
                "sb-fixture-base",
            ),
            _cand(
                "g1-c0",
                "g0-c0",
                "parent-feedback-revision",
                "performance_met",
                6.553,
                7.346,
                False,
                "correctness/test count first; fastest supervisor-measured median among tied passing candidates; noisy finite-run estimate",
                "sb-fixture-g1c0",
                "sb-fixture-g0c0",
                gen=1,
            ),
        ],
    }
    completed["candidates"][0]["code"] = _code("MARKER-COMPLETED-G0C0")
    completed["candidates"][0]["explanation"] = "fixture explanation (display only)"
    live_c0 = _cand(
        "g0-c0",
        None,
        "sorted-bisect",
        "performance_met",
        6.9,
        7.1,
        False,
        None,
        "sb-fixture-live-g0c0",
        "sb-fixture-live-base",
    )
    live = {
        "run_id": LIVE,
        "status": "running",
        "started_at": now,
        "model_calls": 1,
        "best_candidate_id": None,
        "warnings": [],
        "resources": [],
        "candidates": [live_c0],
    }
    for run_id, summary in ((COMPLETED, completed), (LIVE, live)):
        (root / run_id).mkdir(parents=True)
        (root / run_id / "summary.json").write_text(json.dumps(summary))
    events = [
        {"event": "run_started"},
        {"event": "candidate_started", "candidate_id": "g0-c0", "status": "generating"},
        {
            "event": "candidate_result",
            "candidate_id": "g0-c0",
            "status": "performance_met",
            "feedback": live_c0["feedback"],
        },
    ]
    (root / LIVE / "events.jsonl").write_text(
        "".join(
            json.dumps({"timestamp": now, "run_id": LIVE, **e}) + "\n" for e in events
        )
    )
    for name in EVIDENCE:
        (root / name).mkdir()
        shutil.copy(REPO / "evidence" / name / "summary.json", root / name)


@pytest.mark.skipif(
    not (CHROME and _node_has_websocket()),
    reason="needs Chromium and Node with global WebSocket",
)
def test_dashboard_elements_in_real_browser(tmp_path, monkeypatch):
    root = tmp_path / "runs"
    root.mkdir()
    _write_fixture_root(root)
    done = tmp_path / "fake-job-done"
    spawned = []

    def fake_popen(args, **kwargs):
        spawned.append(args)
        return SimpleNamespace(poll=lambda: 0 if done.exists() else None)

    monkeypatch.setattr(
        web, "subprocess", SimpleNamespace(Popen=fake_popen, STDOUT=subprocess.STDOUT)
    )
    job = {"process": None, "log": None}
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(root, 0, job=job))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}/"
    try:
        result = subprocess.run(
            [
                NODE,
                str(REPO / "tests" / "e2e" / "dashboard_e2e.mjs"),
                *("--url", base, "--chrome", CHROME, "--root", str(root)),
                *("--live", LIVE, "--completed", COMPLETED, "--done", str(done)),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    finally:
        server.shutdown()
        server.server_close()
        if job["log"]:
            job["log"].close()
    lines = result.stdout.strip().splitlines()
    report = json.loads(lines[-1]) if lines else {"checks": [], "problems": []}
    failed = [c for c in report["checks"] if not c["ok"]]
    print(
        "\n".join(
            f"{'ok ' if c['ok'] else 'FAIL'} {c['name']}" for c in report["checks"]
        )
    )
    assert result.returncode == 0 and not failed and len(report["checks"]) >= 40, (
        failed,
        result.stderr[-2000:],
    )
    assert spawned == [
        [sys.executable, "-m", "kiss_engine.cli", "run"]
        + ["--rounds", "2", "--width", "2", "--max-candidates", "3"]
        + ["--max-sandboxes", "6", "--max-model-calls", "8"]
    ]


def test_ui_launch_flags_are_accepted_by_cli():
    out = subprocess.run(
        [sys.executable, "-m", "kiss_engine.cli", "run", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert out.returncode == 0
    for flag in (
        "--rounds",
        "--width",
        "--max-candidates",
        "--max-sandboxes",
        "--max-model-calls",
    ):
        assert flag in out.stdout


def test_report_endpoint_renders_live_summary_before_report_html(tmp_path):
    run_dir = tmp_path / LIVE
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(
        json.dumps({"run_id": LIVE, "status": "running", "candidates": []})
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path, 0))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        r = httpx.get(f"{base}/report/{LIVE}", timeout=10)
        assert r.status_code == 200 and "LIVE RUN IN PROGRESS" in r.text
        assert httpx.get(f"{base}/report/{COMPLETED}", timeout=10).status_code == 404
    finally:
        server.shutdown()
        server.server_close()
