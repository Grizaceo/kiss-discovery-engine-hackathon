"""OFFLINE fakes only. No fixture solution is imported/executed on the host."""

import ast
import json
import math

import httpx
import pytest

from kiss_engine.engine import Limits, rank
from kiss_engine.harness import build_harness, extract_worker_source, parse_result
from kiss_engine.mercury import GenerationError, Mercury, validate_code
from kiss_engine.report import render_report, speed_verdict
from kiss_engine.runtime import Ledger, Sandboxes, checked, deadline, load_secrets
from kiss_engine.smoke import expect
from kiss_engine.web import list_runs, make_handler, platform_evidence

FAKE_CODE = "def count_pairs(a,b,lower,upper):\n    return 0\n"


def envelope(content=None, finish="stop", **extra):
    return {
        "model": "mercury-2.5",
        "choices": [
            {
                "finish_reason": finish,
                "message": {
                    "content": content
                    if content is not None
                    else json.dumps(
                        {
                            "approach": "offline fixture",
                            "code": FAKE_CODE,
                            "explanation": "not Mercury; never executed",
                        }
                    )
                },
            }
        ],
        "usage": {"total_tokens": 5},
        **extra,
    }


def make_client(tmp_path, responses, max_calls=5):
    ledger = Ledger("offline-test", root=tmp_path)

    def handler(request):
        status, body = responses.pop(0)
        assert str(request.url) == "https://api.inceptionlabs.ai/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "mercury-2.5"
        assert payload["reasoning_effort"] == "instant"
        assert payload["temperature"] == 0.75
        return httpx.Response(status, json=body)

    client = httpx.Client(
        base_url="https://api.inceptionlabs.ai/v1/",
        transport=httpx.MockTransport(handler),
    )
    return Mercury(
        "FAKE_OFFLINE_KEY",
        ledger,
        max_calls=max_calls,
        client=client,
        sleeper=lambda _: None,
    ), ledger


def test_generation_validates_ast_without_host_execution(tmp_path):
    mercury, ledger = make_client(tmp_path, [(200, envelope())])
    result = mercury.generate("test0", "sorted-bisect")
    assert result["code"] == FAKE_CODE
    assert len(result["code_sha256"]) == 64
    assert (ledger.path / "candidates/test0/response.json").is_file()
    mercury.close()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (envelope(finish="length"), "truncated_generation"),
        ({"choices": []}, "empty_generation"),
        (envelope(content="  "), "empty_generation"),
        (envelope(content="not json"), "invalid_generation"),
        (
            envelope(
                content=json.dumps(
                    {"approach": "fixture", "code": "", "explanation": "x"}
                )
            ),
            "empty_generation",
        ),
        (
            envelope(
                content=json.dumps(
                    {
                        "approach": "fixture",
                        "code": "def count_pairs(:",
                        "explanation": "x",
                    }
                )
            ),
            "compilation_error",
        ),
        ([], "invalid_generation"),
        ({"choices": ["bad"]}, "invalid_generation"),
        (envelope(model="other-model"), "api_error"),
    ],
)
def test_generation_error_categories(tmp_path, payload, expected):
    m, _ = make_client(tmp_path, [(200, payload)], max_calls=1)
    with pytest.raises(GenerationError) as exc:
        m.generate("fixture", "two-pointer")
    assert exc.value.status == expected
    m.close()


def test_429_bounded_retry_does_not_become_candidate_failure(tmp_path):
    m, ledger = make_client(tmp_path, [(429, {}), (200, envelope())])
    assert m.generate("fixture", "two-pointer")["code"] == FAKE_CODE
    assert m.calls == 2
    assert (
        len(
            [
                json.loads(l)
                for l in (ledger.path / "events.jsonl").read_text().splitlines()
                if json.loads(l)["event"] == "generation_http"
            ]
        )
        == 2
    )
    m.close()


def test_429_respects_model_call_budget(tmp_path):
    m, _ = make_client(tmp_path, [(429, {})], max_calls=1)
    with pytest.raises(GenerationError, match="429"):
        m.generate("fixture", "two-pointer")
    assert m.calls == 1
    m.close()


def test_api_http_failure_has_no_fallback(tmp_path):
    m, _ = make_client(tmp_path, [(401, {})])
    with pytest.raises(GenerationError) as exc:
        m.generate("fixture", "two-pointer")
    assert exc.value.status == "api_error"
    assert m.calls == 1
    m.close()


def test_call_limit_stops_without_request(tmp_path):
    m, _ = make_client(tmp_path, [], max_calls=0)
    with pytest.raises(GenerationError) as exc:
        m.generate("fixture", "two-pointer")
    assert exc.value.status == "call_limit"
    assert m.calls == 0
    m.close()


def test_child_prompt_contains_only_its_parent(tmp_path):
    m, ledger = make_client(tmp_path, [(200, envelope())])
    parent = {
        "code": FAKE_CODE + "# own parent marker",
        "feedback": {"status": "test_failure", "errors": [{"got": 0, "expected": 4}]},
    }
    m.generate("child", "parent-feedback-revision", parent=parent)
    prompt = json.loads((ledger.path / "candidates/child/prompt.json").read_text())
    text = prompt["messages"][1]["content"]
    assert "own parent marker" in text and "test_failure" in text
    m.close()


@pytest.mark.parametrize(
    "code",
    [
        "import os\ndef count_pairs(a,b,c,d):return 0",
        'def count_pairs(a,b,c,d):return eval("0")',
        "def other():return 0",
    ],
)
def test_invalid_contract_rejected_without_execution(code):
    with pytest.raises(GenerationError):
        validate_code({"approach": "fake", "code": code, "explanation": "offline"})


@pytest.mark.parametrize(
    "override",
    [
        {"rounds": 0},
        {"width": 3},
        {"max_candidates": True},
        {"max_sandboxes": 99},
        {"search_seconds": 601},
        {"benchmark_n": 0},
    ],
)
def test_config_limits(override):
    with pytest.raises(ValueError):
        Limits(**override).validate()


def test_selection_never_rewards_fast_incorrect_code():
    wrong = {
        "candidate_id": "wrong",
        "feedback": {
            "status": "test_failure",
            "tests_passed": 59,
            "candidate_ms": 0.001,
        },
    }
    right = {
        "candidate_id": "right",
        "feedback": {"status": "correct", "tests_passed": 60, "candidate_ms": 100},
    }
    assert min([wrong, right], key=rank) is right


def test_nonfinite_rank_not_rewarded():
    bad = {
        "candidate_id": "bad",
        "feedback": {"status": "correct", "tests_passed": 60, "candidate_ms": math.nan},
    }
    good = {
        "candidate_id": "good",
        "feedback": {"status": "correct", "tests_passed": 60, "candidate_ms": 1},
    }
    assert min([bad, good], key=rank) is good


def test_resource_creation_cap_no_remote_call():
    adapter = Sandboxes.__new__(Sandboxes)
    adapter.attempts = 1
    adapter.max_created = 1
    with pytest.raises(RuntimeError, match="limit"):
        adapter.reserve()


def test_ledger_redacts_known_secrets_and_appends(tmp_path):
    ledger = Ledger("offline", root=tmp_path)
    ledger.secrets = ["FAKE_SECRET_FIXTURE"]
    ledger.event("first", error="token FAKE_SECRET_FIXTURE")
    ledger.event("second", value=2)
    raw = (ledger.path / "events.jsonl").read_text()
    assert "FAKE_SECRET_FIXTURE" not in raw
    rows = [json.loads(l) for l in raw.splitlines()]
    assert [r["event"] for r in rows] == ["first", "second"]


def test_harness_security_regressions_ast_only():
    source = build_harness(7)
    tree = ast.parse(source)
    terminate = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "terminate"
    )
    assert not any(
        isinstance(n, ast.Attribute) and n.attr == "kill" for n in ast.walk(terminate)
    )
    assert "worker_pid = None  # Untrusted" in source
    assert "candidate_samples_ms" in source
    assert "worker timing samples must be finite" in source
    assert "MAX_ADDRESS_SPACE_BYTES = 512 * 1024 ** 2" in extract_worker_source(source)
    assert "candidate mutated caller inputs" in extract_worker_source(source)
    choose = next(
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "choose_interpreter"
    )
    first = choose.body[0].value.elts[0]
    assert ast.literal_eval(first) == "/usr/bin/python3"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, 0])
def test_parser_rejects_invalid_measurements(value):
    payload = {
        "protocol_version": 1,
        "status": "correct",
        "tests_passed": 60,
        "total": 60,
        "compile_ok": True,
        "errors": [],
        "candidate_ms": value,
        "baseline_ms": 1,
        "benchmark": {},
    }
    with pytest.raises(ValueError):
        parse_result(json.dumps(payload))


def test_report_escapes_model_and_user_content():
    s = {
        "run_id": "test",
        "candidates": [
            {"candidate_id": "x", "code": "<script>alert(1)</script>", "feedback": {}}
        ],
    }
    html = render_report(s)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_dashboard_reflects_real_event_states(tmp_path):
    path = tmp_path / "search-fixture"
    path.mkdir()
    (path / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "search-fixture",
                "status": "running",
                "candidates": [
                    {
                        "candidate_id": "g0-c0",
                        "status": "correct",
                        "approach": "sorted-bisect",
                        "selection_reason": "selected in round 0",
                    }
                ],
            }
        )
    )
    events = [
        {
            "event": "candidate_started",
            "candidate_id": "g0-c0",
            "status": "generating",
            "generation": 0,
        },
        {
            "event": "candidate_started",
            "candidate_id": "a",
            "status": "generating",
            "generation": 1,
        },
        {
            "event": "candidate_evaluating",
            "candidate_id": "a",
            "sandbox_id": "FAKE_VM",
            "forked_from": "FAKE_BASE",
        },
    ]
    (path / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    rows = list_runs(tmp_path)
    by_id = {c["candidate_id"]: c for c in rows[0]["candidates"]}
    assert by_id["g0-c0"]["approach"] == "sorted-bisect"
    assert by_id["g0-c0"]["selection_reason"] == "selected in round 0"
    assert by_id["a"]["status"] == "evaluating"
    assert by_id["a"]["sandbox_id"] == "FAKE_VM"


def test_truncated_generation_retries_within_explicit_budget(tmp_path):
    m, ledger = make_client(
        tmp_path, [(200, envelope(finish="length")), (200, envelope())]
    )
    result = m.generate("child", "parent-feedback-revision")
    assert result["code"] == FAKE_CODE and m.calls == 2
    second = json.loads(
        (ledger.path / "candidates/child/prompt-attempt-2.json").read_text()
    )
    assert second["max_completion_tokens"] == 5000
    assert (ledger.path / "candidates/child/response-attempt-1.json").is_file()
    m.close()


def test_invalid_structured_model_content_has_bounded_retry(tmp_path):
    m, ledger = make_client(
        tmp_path, [(200, envelope(content='[["int"]]')), (200, envelope())]
    )
    assert m.generate("child", "parent-feedback-revision")["code"] == FAKE_CODE
    assert m.calls == 2
    second = json.loads(
        (ledger.path / "candidates/child/prompt-attempt-2.json").read_text()
    )
    assert "Previous response violated" in second["messages"][-1]["content"]
    m.close()


def make_verdict(status="correct", tests_passed=60, candidate_ms=2.0, baseline_ms=1.0):
    verdict = {
        "protocol_version": 1,
        "status": status,
        "tests_passed": tests_passed,
        "total": 60,
        "compile_ok": status != "compilation_error",
        "errors": [],
        "candidate_ms": candidate_ms
        if status in {"correct", "performance_met"}
        else None,
        "baseline_ms": baseline_ms
        if status in {"correct", "performance_met"}
        else None,
        "benchmark": {
            "candidate_count": 3,
            "baseline_count": 3,
            "expected_count": 3,
            "n": 1000,
            "reps": 3,
            "warmup": 1,
        }
        if status in {"correct", "performance_met"}
        else None,
    }
    exit_code = (
        0
        if status in {"correct", "performance_met"}
        else 2
        if status == "harness_error"
        else 10
    )
    return exit_code, verdict


def install_offline_search_fakes(monkeypatch, verdicts=None):
    from types import SimpleNamespace

    from kiss_engine import engine

    queue = list(verdicts or [])
    monkeypatch.setattr(
        engine, "load_secrets", lambda: {"createos": "FAKE", "mercury": "FAKE"}
    )

    class FakeSandboxes:
        def __init__(self, *args, **kwargs):
            self.attempts = 0
            self.owned = []

        def create(self):
            self.attempts += 1
            box = SimpleNamespace(id="FAKE_BASE", parent=None)
            self.owned.append(box)
            return box

        def fork(self, parent):
            self.attempts += 1
            box = SimpleNamespace(id=f"FAKE_CHILD_{self.attempts}", parent=parent.id)
            self.owned.append(box)
            return box

        def upload(self, *args):
            pass

        def pause(self, *args):
            pass

        def destroy(self, *args):
            pass

        def exec(self, *args, **kwargs):
            exit_code, verdict = queue.pop(0) if queue else make_verdict()
            return {
                "exit_code": exit_code,
                "standard_output": json.dumps(verdict),
                "standard_error": "",
            }

        def cleanup(self):
            return [
                {"sandbox_id": b.id, "status": "destroyed", "verified": True}
                for b in self.owned
            ]

    class FakeMercury:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def generate(self, *args, **kwargs):
            self.calls += 1
            return {
                "code": FAKE_CODE,
                "code_sha256": f"FAKE_OFFLINE_HASH_{self.calls}",
                "approach": "offline fixture",
                "provider": "OFFLINE_TEST_FAKE",
            }

        def close(self):
            pass

    monkeypatch.setattr(engine, "Sandboxes", FakeSandboxes)
    monkeypatch.setattr(engine, "Mercury", FakeMercury)
    monkeypatch.setattr(engine, "checked", lambda *args, **kwargs: "OFFLINE_FIXTURE")
    monkeypatch.setattr(engine, "projection", lambda box: {"forked_from": box.parent})
    return engine


@pytest.mark.parametrize(
    ("override", "expected"),
    [
        ({"max_candidates": 1}, "max_candidates"),
        ({"max_candidates": 2}, "max_candidates"),
        ({"max_model_calls": 1}, "max_model_calls"),
        ({"max_sandboxes": 2}, "max_sandboxes"),
    ],
)
def test_search_stops_at_each_configured_cap_offline(
    tmp_path, monkeypatch, override, expected
):
    monkeypatch.chdir(tmp_path)
    engine = install_offline_search_fakes(monkeypatch)
    config = {
        "rounds": 3,
        "width": 2,
        "max_candidates": 5,
        "max_model_calls": 5,
        "max_sandboxes": 6,
    } | override
    result = engine.run_search(engine.Limits(**config))
    assert result["stop_reason"] == expected
    expected_count = 2 if override.get("max_candidates") == 2 else 1
    assert result["model_calls"] == expected_count
    assert len(result["candidates"]) == expected_count
    assert all(c["selection_reason"] for c in result["candidates"])
    if expected_count == 2:
        assert "not selected" in result["candidates"][1]["selection_reason"]
    assert all(r["status"] == "destroyed" for r in result["resources"])


def test_all_incorrect_run_has_no_best_candidate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    verdicts = [make_verdict("test_failure", tests_passed=5) for _ in range(3)]
    engine = install_offline_search_fakes(monkeypatch, verdicts=verdicts)
    result = engine.run_search(
        engine.Limits(rounds=2, width=2, max_candidates=3, max_sandboxes=4)
    )
    assert result["best_candidate_id"] is None
    assert result["status"] == "failed"
    assert result["revision_parent_id"] is not None
    assert len(result["candidates"]) == 3


def test_superseded_parent_keeps_selection_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    verdicts = [
        make_verdict("correct", tests_passed=60, candidate_ms=5.0),
        make_verdict("correct", tests_passed=60, candidate_ms=8.0),
        make_verdict("correct", tests_passed=60, candidate_ms=3.0),
    ]
    engine = install_offline_search_fakes(monkeypatch, verdicts=verdicts)
    result = engine.run_search(
        engine.Limits(rounds=2, width=2, max_candidates=3, max_sandboxes=4)
    )
    by_id = {c["candidate_id"]: c for c in result["candidates"]}
    assert result["best_candidate_id"] == "g1-c0"
    assert "selected in round(s) [0]" in by_id["g0-c0"]["selection_reason"]
    assert "superseded by g1-c0" in by_id["g0-c0"]["selection_reason"]


def test_parent_remains_best_when_child_slower(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    verdicts = [
        make_verdict("correct", tests_passed=60, candidate_ms=3.0),
        make_verdict("correct", tests_passed=60, candidate_ms=4.5),
    ]
    engine = install_offline_search_fakes(monkeypatch, verdicts=verdicts)
    result = engine.run_search(
        engine.Limits(rounds=2, width=1, max_candidates=2, max_sandboxes=3)
    )
    by_id = {c["candidate_id"]: c for c in result["candidates"]}
    assert result["best_candidate_id"] == "g0-c0"
    assert "not selected" in by_id["g1-c0"]["selection_reason"]


def test_incorrect_child_never_becomes_best(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    verdicts = [
        make_verdict("correct", tests_passed=60, candidate_ms=5.0),
        make_verdict("test_failure", tests_passed=12),
    ]
    engine = install_offline_search_fakes(monkeypatch, verdicts=verdicts)
    result = engine.run_search(
        engine.Limits(rounds=2, width=1, max_candidates=2, max_sandboxes=3)
    )
    by_id = {c["candidate_id"]: c for c in result["candidates"]}
    assert result["best_candidate_id"] == "g0-c0"
    assert result["status"] == "completed"
    assert "not selected" in by_id["g1-c0"]["selection_reason"]


def test_render_report_without_correct_candidate_has_no_selected_winner():
    summary = {
        "run_id": "search-no-winner",
        "status": "failed",
        "stop_reason": "max_rounds",
        "best_candidate_id": None,
        "revision_parent_id": "g0-c0",
        "candidates": [
            {
                "candidate_id": "g0-c0",
                "status": "test_failure",
                "feedback": {"status": "test_failure", "tests_passed": 5, "total": 60},
            }
        ],
    }
    html = render_report(summary)
    assert "SELECTED WINNER" not in html
    assert "Revision parent" in html
    assert "g0-c0" in html


def test_live_selection_event_with_failing_parent_does_not_set_best(tmp_path):
    path = tmp_path / "search-live-fail"
    path.mkdir()
    (path / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "search-live-fail",
                "status": "running",
                "best_candidate_id": None,
                "candidates": [
                    {"candidate_id": "g0-c0", "status": "test_failure"},
                ],
            }
        )
    )
    events = [
        {
            "event": "selection",
            "candidate_id": "g0-c0",
            "role": "revision_parent",
            "passing": False,
            "best_candidate_id": None,
            "revision_parent_id": "g0-c0",
            "reason": "selected as revision parent only",
        }
    ]
    (path / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    rows = list_runs(tmp_path)
    assert rows[0]["best_candidate_id"] is None
    assert rows[0]["revision_parent_id"] == "g0-c0"


def test_speed_verdict_noise_band_and_real_run_ratios():
    # 215022 g1-c0: 6.553484 / 7.346338 = 0.892x, agreement=False -> parity
    f_215022_g1c0 = {
        "candidate_ms": 6.553484,
        "baseline_ms": 7.346338,
        "benchmark": {"agreement": False},
    }
    assert (
        speed_verdict(f_215022_g1c0)
        == "0.89× baseline · parity within measurement noise"
    )
    # 200300 g0-c1: 5.678 / 6.828 = 0.832x, agreement=True -> faster beyond the noise band
    f_200300_g0c1 = {
        "candidate_ms": 5.678,
        "baseline_ms": 6.828,
        "benchmark": {"agreement": True},
    }
    assert (
        speed_verdict(f_200300_g0c1) == "0.83× baseline · faster beyond the noise band"
    )
    # 215022 g0-c1: 9.666881 / 7.165880 = 1.349x -> slower
    f_215022_g0c1 = {
        "candidate_ms": 9.666881,
        "baseline_ms": 7.165880,
        "benchmark": {"agreement": True},
    }
    assert speed_verdict(f_215022_g0c1) == "1.35× baseline · slower"
    assert speed_verdict({}) == "not benchmarked"


def test_load_secrets_uses_mercury_env_file_without_hardcoded_path(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    for var in (
        "CREATEOS_API_KEY",
        "CREATEOS_PROJECT_API_KEY",
        "CREATEOS_PLAN_API_KEY",
        "MERCURY_API_KEY",
        "INCEPTION_API_KEY",
        "MERCURY_ENV_FILE",
    ):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".env").write_text("CREATEOS_API_KEY=FAKE_CREATEOS_LOCAL\n")
    with pytest.raises(RuntimeError, match="Missing credential"):
        load_secrets()
    ext_mercury = tmp_path / "external.mercury.env"
    ext_mercury.write_text("MERCURY_API_KEY=FAKE_MERCURY_EXT\n")
    (tmp_path / ".env").write_text(
        f"CREATEOS_API_KEY=FAKE_CREATEOS_LOCAL\nMERCURY_ENV_FILE={ext_mercury}\n"
    )
    assert load_secrets() == {
        "createos": "FAKE_CREATEOS_LOCAL",
        "mercury": "FAKE_MERCURY_EXT",
    }


def test_smoke_expect_raises_runtime_error():
    expect("base-marker", "base-marker", "marker check")
    with pytest.raises(RuntimeError, match="Smoke check failed"):
        expect("wrong", "base-marker", "marker check")


def test_render_report_static_omits_local_back_link():
    summary = {"run_id": "search-static", "status": "completed", "candidates": []}
    assert "← Back to local experiment ledger" in render_report(summary, static=False)
    assert "← Back to local experiment ledger" not in render_report(
        summary, static=True
    )


def test_platform_evidence_extracts_selected_fields_offline(tmp_path):
    smoke_dir = tmp_path / "smoke-20261017T200218-804c8e"
    smoke_dir.mkdir()
    (smoke_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "smoke-20261017T200218-804c8e",
                "ok": True,
                "inheritance_verified": True,
                "independence_verified": True,
                "concurrent_running_observed": 2,
                "egress": {
                    "https://pypi.org/simple/": {"reachable": True, "status": 200}
                },
                "cleanup": [{"sandbox_id": "sb-1", "status": "destroyed"}],
                "untrusted_extra": "ignored",
            }
        )
    )
    fix_dir = tmp_path / "fixtures-20261017T195514-b9747e"
    fix_dir.mkdir()
    (fix_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "fixtures-20261017T195514-b9747e",
                "ok": True,
                "results": [
                    {
                        "fixture": "timing-spoof",
                        "expected": "protocol_error",
                        "actual": "protocol_error",
                        "ok": True,
                        "feedback": {"huge": "omitted"},
                    }
                ],
                "cleanup": [{"sandbox_id": "sb-2", "status": "destroyed"}],
            }
        )
    )
    audit_dir = tmp_path / "audit-20261017T215138-6151e4"
    audit_dir.mkdir()
    (audit_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "audit-20261017T215138-6151e4",
                "owned_count": 34,
                "destroyed_count": 34,
                "unresolved": [],
                "usage_events": 16,
                "provider_reported_tokens": {"total_tokens": 20350},
                "resources": [{"id": "sb-raw"}],
            }
        )
    )
    ev = platform_evidence(tmp_path)
    assert ev["smoke"]["inheritance_verified"] is True
    assert ev["smoke"]["independence_verified"] is True
    assert "untrusted_extra" not in ev["smoke"]
    assert ev["fixtures"]["results"] == [
        {
            "fixture": "timing-spoof",
            "expected": "protocol_error",
            "actual": "protocol_error",
            "ok": True,
        }
    ]
    assert ev["audit"]["destroyed_count"] == 34
    assert ev["audit"]["owned_count"] == 34
    assert ev["audit"]["unresolved"] == []
    assert ev["audit"]["provider_reported_tokens"]["total_tokens"] == 20350
    assert "resources" not in ev["audit"]


def test_ledger_artifact_writes_atomically_via_replace(tmp_path, monkeypatch):
    import os

    calls = []
    real_replace = os.replace

    def spy_replace(src, dst):
        calls.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    ledger = Ledger("atomic", root=tmp_path)
    ledger.secrets = ["SECRET_TOKEN"]
    ledger.artifact("summary.json", {"note": "has SECRET_TOKEN"})
    assert len(calls) == 1
    assert calls[0][1] == ledger.path / "summary.json"
    assert not list(ledger.path.glob("*.tmp"))
    assert "SECRET_TOKEN" not in (ledger.path / "summary.json").read_text()


def test_k19_duplicate_saves_summary_none_output_checked_and_harness_ast(
    tmp_path, monkeypatch
):
    from dataclasses import dataclass
    from types import SimpleNamespace

    monkeypatch.chdir(tmp_path)
    engine = install_offline_search_fakes(monkeypatch)

    class DupMercury:
        def __init__(self, *args, **kwargs):
            self.calls = 0

        def generate(self, *args, **kwargs):
            self.calls += 1
            return {
                "code": FAKE_CODE,
                "code_sha256": "SAME_HASH",
                "approach": "offline fixture",
                "provider": "OFFLINE_TEST_FAKE",
            }

        def close(self):
            pass

    monkeypatch.setattr(engine, "Mercury", DupMercury)
    result = engine.run_search(
        engine.Limits(rounds=1, width=2, max_candidates=2, max_sandboxes=3)
    )
    assert result["candidates"][1]["status"] == "duplicate"
    saved = json.loads(
        (tmp_path / "runs" / result["run_id"] / "summary.json").read_text()
    )
    assert saved["candidates"][1]["status"] == "duplicate"

    @dataclass
    class FakeResult:
        exit_code: int = 0
        stdout: str | None = None
        stderr: str | None = None
        standard_output: str | None = "ok"
        standard_error: str | None = None

    adapter = Sandboxes.__new__(Sandboxes)
    adapter.ledger = Ledger("exec-none", root=tmp_path)
    adapter.op = lambda name, fn, **kw: SimpleNamespace(result=FakeResult())
    box = SimpleNamespace(
        id="sb-1", run_command=lambda *a, **k: SimpleNamespace(result=FakeResult())
    )
    out = adapter.exec(box, "echo")
    assert out["stdout"] is None
    assert checked(adapter, box, "echo") == "ok"

    source = build_harness(7)
    tree = ast.parse(source)
    assert tree is not None
    assert "authoritative_candidate.append(net if net > 0 else wall)" not in source
    assert "authoritative_candidate.append(net)" in source


def test_nested_deadline_respects_outer_remaining_time():
    import time

    started = time.monotonic()
    with pytest.raises(TimeoutError), deadline(1), deadline(3):
        time.sleep(2)
    elapsed = time.monotonic() - started
    assert elapsed < 1.3


def test_stale_running_run_shown_as_stale_without_rewriting_summary(tmp_path):
    from datetime import UTC, datetime, timedelta

    path = tmp_path / "search-stale"
    path.mkdir()
    old_ts = (datetime.now(UTC) - timedelta(seconds=950)).isoformat()
    raw_summary = {
        "run_id": "search-stale",
        "status": "running",
        "started_at": old_ts,
        "candidates": [],
    }
    (path / "summary.json").write_text(json.dumps(raw_summary))
    (path / "events.jsonl").write_text(
        json.dumps({"event": "search_preparing", "timestamp": old_ts}) + "\n"
    )
    rows = list_runs(tmp_path)
    assert rows[0]["status"] == "stale"
    assert json.loads((path / "summary.json").read_text())["status"] == "running"


def test_web_handler_http_security_and_validation(tmp_path, monkeypatch):
    import subprocess
    import threading
    from http.server import ThreadingHTTPServer
    from types import SimpleNamespace

    spawned = []

    def fake_popen(args, **kwargs):
        spawned.append(args)
        return SimpleNamespace(poll=lambda: 0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    job = {"process": None, "log": None}
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path, 0, job=job))
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    origin = base
    try:
        with httpx.Client() as client:
            # Invalid Host -> 403
            r = client.get(f"{base}/api/runs", headers={"Host": "evil.example:8097"})
            assert r.status_code == 403

            # POST without valid Origin -> 403
            r = client.post(
                f"{base}/api/run",
                headers={"Content-Type": "application/json"},
                content=b'{"rounds":1}',
            )
            assert r.status_code == 403
            r = client.post(
                f"{base}/api/run",
                headers={
                    "Origin": "http://evil.example",
                    "Content-Type": "application/json",
                },
                content=b'{"rounds":1}',
            )
            assert r.status_code == 403

            # Content-Type != application/json -> 415
            r = client.post(
                f"{base}/api/run",
                headers={"Origin": origin, "Content-Type": "text/plain"},
                content=b'{"rounds":1}',
            )
            assert r.status_code == 415

            # Empty body or >1000 bytes -> 400
            r = client.post(
                f"{base}/api/run",
                headers={"Origin": origin, "Content-Type": "application/json"},
                content=b"",
            )
            assert r.status_code == 400
            r = client.post(
                f"{base}/api/run",
                headers={"Origin": origin, "Content-Type": "application/json"},
                content=b" " * 1001,
            )
            assert r.status_code == 400

            # run-id with .. or without search- prefix -> 400
            r = client.get(f"{base}/report/search-..bad")
            assert r.status_code == 400
            r = client.get(f"{base}/report/smoke-20261017T200218-804c8e")
            assert r.status_code == 400

            # Valid POST with monkeypatched Popen -> 202
            r = client.post(
                f"{base}/api/run",
                headers={"Origin": origin, "Content-Type": "application/json"},
                content=b'{"rounds":1,"width":1,"max_candidates":1}',
            )
            assert r.status_code == 202
            assert len(spawned) == 1
    finally:
        server.shutdown()
        server.server_close()
        if job["log"]:
            job["log"].close()


def test_cleanup_adopts_missing_run_boxes_and_bounds_budget(tmp_path):
    from dataclasses import dataclass
    from types import SimpleNamespace

    @dataclass
    class BoxData:
        id: str
        name: str
        status: str = "destroyed"
        forked_from: str = ""

    def make_box(id, name, forked_from=""):
        b = SimpleNamespace(
            id=id,
            status="destroyed",
            data=BoxData(id=id, name=name, forked_from=forked_from),
            refresh=lambda: None,
            destroy=lambda: None,
        )
        return b

    ledger = Ledger("search", root=tmp_path)
    run_name = ("kiss-" + ledger.run_id[-17:]).lower()
    base = make_box("sb-base", run_name)
    orphan_child = make_box("sb-orphan-child", "forked-box", forked_from="sb-base")
    unrelated = make_box("sb-other-run", "kiss-unrelated")

    adapter = Sandboxes.__new__(Sandboxes)
    adapter.ledger = ledger
    adapter.initial_ids = set()
    adapter.owned = {"sb-base": base}
    adapter.op = lambda name, fn, **kw: fn()
    adapter.client = SimpleNamespace(
        list_sandboxes=lambda opts: [base, orphan_child, unrelated],
        close=lambda: None,
    )
    results = adapter.cleanup(budget_seconds=60)
    assert {r["sandbox_id"] for r in results} == {"sb-base", "sb-orphan-child"}
    assert "sb-other-run" not in adapter.owned
    assert all(r["status"] == "destroyed" for r in results)

    # Budget exhausted -> remaining boxes recorded as cleanup_pending
    adapter2 = Sandboxes.__new__(Sandboxes)
    adapter2.ledger = Ledger("search", root=tmp_path)
    adapter2.initial_ids = set()
    adapter2.owned = {"sb-1": make_box("sb-1", "a"), "sb-2": make_box("sb-2", "b")}
    adapter2.op = lambda name, fn, **kw: fn()
    adapter2.client = SimpleNamespace(
        list_sandboxes=lambda opts: [], close=lambda: None
    )
    pending = adapter2.cleanup(budget_seconds=0)
    assert [r["status"] for r in pending] == ["cleanup_pending", "cleanup_pending"]
