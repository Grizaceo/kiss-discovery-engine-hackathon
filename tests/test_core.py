"""OFFLINE fakes only. No fixture solution is imported/executed on the host."""

import ast
import json
import math

import httpx
import pytest

from kiss_engine.engine import Limits, rank
from kiss_engine.harness import build_harness, extract_worker_source, parse_result
from kiss_engine.mercury import GenerationError, Mercury, validate_code
from kiss_engine.report import render_report
from kiss_engine.runtime import Ledger, Sandboxes
from kiss_engine.web import list_runs

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
        json.dumps({"run_id": "search-fixture", "status": "running", "candidates": []})
    )
    events = [
        {
            "event": "candidate_started",
            "candidate_id": "a",
            "status": "generating",
            "generation": 0,
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
    assert rows[0]["candidates"][0]["status"] == "evaluating"
    assert rows[0]["candidates"][0]["sandbox_id"] == "FAKE_VM"


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
    from types import SimpleNamespace

    from kiss_engine import engine

    monkeypatch.chdir(tmp_path)
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
            verdict = {
                "protocol_version": 1,
                "status": "correct",
                "tests_passed": 60,
                "total": 60,
                "compile_ok": True,
                "errors": [],
                "candidate_ms": 2,
                "baseline_ms": 1,
                "benchmark": {
                    "candidate_count": 3,
                    "baseline_count": 3,
                    "expected_count": 3,
                    "n": 1000,
                    "reps": 3,
                    "warmup": 1,
                },
            }
            return {
                "exit_code": 0,
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
