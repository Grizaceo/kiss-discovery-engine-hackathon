"""Offline tests for the trusted remote harness source builder.

Everything here is static: generated source is parsed with ``ast``, inspected as
text, or fed to the host-side result parser. No candidate/solution code is imported
or executed, no sandbox is contacted and nothing is written outside ``tmp_path``.
"""

from __future__ import annotations

import ast
import builtins
import json

import pytest

from kiss_engine import harness

# --------------------------------------------------------------------------- helpers


def _supervisor_tree(seed: int = 1234, benchmark_n: int = 20000) -> ast.Module:
    return ast.parse(harness.build_harness(seed, benchmark_n=benchmark_n))


def _module_assignments(tree: ast.Module) -> dict:
    """Map module-level ``NAME = <literal>`` to the literal value."""
    found = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                continue
    return found


def _function_defs(tree: ast.Module) -> dict:
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _module_expressions(tree: ast.Module) -> dict:
    """Map module-level ``NAME = <expr>`` to the unparsed expression text."""
    found = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            found[node.targets[0].id] = ast.unparse(node.value)
    return found


def _class_names(tree: ast.Module) -> set:
    return {node.name for node in tree.body if isinstance(node, ast.ClassDef)}


def _called_names(tree: ast.Module) -> set:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _attribute_names(tree: ast.Module) -> set:
    return {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}


def _open_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "open")
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in {"open", "fdopen"}
            )
        )
    ]


def _imported_modules(tree: ast.Module) -> set:
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _valid_result(**overrides) -> dict:
    payload = {
        "protocol_version": harness.PROTOCOL_VERSION,
        "status": "correct",
        "error_type": "correct",
        "phase": "benchmark",
        "tests_passed": 60,
        "total": 60,
        "compile_ok": True,
        "errors": [],
        "candidate_ms": 12.5,
        "baseline_ms": 40.0,
        "speedup": 3.2,
        "benchmark": {
            "n": 20000,
            "reps": 3,
            "warmup": 1,
            "candidate_count": 1,
            "baseline_count": 1,
            "expected_count": 1,
        },
        "detail": None,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ builder basics


def test_build_harness_returns_parseable_python_source():
    source = harness.build_harness(7)
    assert isinstance(source, str)
    assert source.startswith("#!/usr/bin/env python3")
    assert ast.parse(source) is not None


def test_build_harness_is_deterministic_and_seed_sensitive():
    assert harness.build_harness(11) == harness.build_harness(11)
    assert harness.build_harness(11) != harness.build_harness(12)


def test_build_harness_embeds_seed_and_benchmark_n():
    source = harness.build_harness(4242, benchmark_n=1234)
    constants = _module_assignments(ast.parse(source))
    assert constants["SEED"] == 4242
    assert constants["BENCHMARK_N"] == 1234
    assert harness.build_harness(1).count("BENCHMARK_N = 20000") == 1


def test_build_harness_rejects_bad_arguments():
    with pytest.raises(TypeError):
        harness.build_harness("7")
    with pytest.raises(TypeError):
        harness.build_harness(True)
    with pytest.raises(TypeError):
        harness.build_harness(1, benchmark_n=2.5)
    with pytest.raises(ValueError):
        harness.build_harness(1, benchmark_n=0)
    with pytest.raises(ValueError):
        harness.build_harness(1, benchmark_n=harness.MAX_BENCHMARK_N + 1)
    with pytest.raises(ValueError):
        harness.build_harness(-1)


def test_build_harness_does_not_touch_the_filesystem(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("build_harness must not use open()")

    monkeypatch.setattr(builtins, "open", explode)
    monkeypatch.setattr(harness, "open", explode, raising=False)
    source = harness.build_harness(3, benchmark_n=64)
    assert "WORKER_SOURCE" in source


# ------------------------------------------------------------------ protocol contract


def test_protocol_version_and_status_enum():
    assert harness.PROTOCOL_VERSION == 1
    assert harness.STATUS_VALUES - harness.REQUIRED_STATUSES == {"harness_error"}
    assert harness.REQUIRED_STATUSES == {
        "compilation_error",
        "test_failure",
        "timeout",
        "protocol_error",
        "correct",
        "performance_met",
    }
    constants = _module_assignments(_supervisor_tree())
    assert constants["PROTOCOL_VERSION"] == harness.PROTOCOL_VERSION
    assert constants["TOTAL_TESTS"] == harness.TOTAL_TESTS == 60
    assert constants["BENCH_WARMUP"] == 1
    assert constants["BENCH_REPS"] == 3
    assert constants["BATCH_CASES"] == 12


def test_supervisor_never_imports_the_candidate():
    tree = _supervisor_tree()
    imported = _imported_modules(tree)
    assert "importlib" not in imported
    assert not imported & {"solution", "candidate_solution", "candidate"}
    source = harness.build_harness(5)
    assert "spec_from_file_location" not in source
    assert "exec_module" not in source
    # exec()/eval() exist only inside the worker text the supervisor carries as data,
    # never in the supervisor's own code.
    assert not {"exec", "eval", "compile"} & _called_names(tree)
    worker_literal = repr(harness.build_worker_source())
    without_worker = source.replace(worker_literal, "<worker>")
    assert "<worker>" in without_worker
    assert "exec(" not in without_worker
    assert harness.CANDIDATE_PATH in source
    assert "supervisor_imports_candidate" in source


def test_worker_imports_candidate_without_importlib():
    tree = ast.parse(harness.build_worker_source())
    assert "importlib" not in _imported_modules(tree)
    source = harness.build_worker_source()
    assert harness.CANDIDATE_PATH in source
    assert "exec(code, namespace)" in source
    assert "count_pairs" in source
    assert "compilation_error" in source
    assert "syntax_error" in source
    assert "missing_callable" in source
    calls = _called_names(tree)
    assert {"compile", "exec"} <= calls


def test_embedded_worker_source_is_recoverable_and_matches_builder():
    source = harness.build_harness(99)
    extracted = harness.extract_worker_source(source)
    assert extracted == harness.build_worker_source()
    assert ast.parse(extracted) is not None
    with pytest.raises(ValueError):
        harness.extract_worker_source("x = 1\n")


def test_worker_source_has_main_guard_and_hello_handshake():
    tree = ast.parse(harness.build_worker_source())
    defs = _function_defs(tree)
    assert {
        "main",
        "load_candidate",
        "handle_batch",
        "handle_bench",
        "open_protocol_channel",
    } <= set(defs)
    guard = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "__name__ == '__main__'"
    ]
    assert len(guard) == 1
    source = harness.build_worker_source()
    assert '"type": "hello"' in source
    assert '"protocol_version": PROTOCOL_VERSION' in source
    assert "__PROTOCOL_VERSION__" not in source
    assert "__BENCH_GEN_SOURCE__" not in source


def test_worker_isolates_candidate_stdout_from_the_protocol():
    tree = ast.parse(harness.build_worker_source())
    attributes = _attribute_names(tree)
    assert {"dup", "dup2", "devnull", "fdopen"} <= attributes
    source = harness.build_worker_source()
    assert "os.dup(1)" in source
    assert "os.dup2(devnull, 1)" in source
    assert "os.dup2(devnull, 2)" in source
    assert "sys.stdout = open(os.devnull, " in source
    assert "sys.stderr = open(os.devnull, " in source
    # a worker crash is reported on the protocol channel, not lost in /dev/null
    assert "install_excepthook" in _function_defs(tree)
    assert "sys.excepthook = hook" in source


def test_worker_writes_no_files_except_devnull():
    tree = ast.parse(harness.build_worker_source())
    assert "shutil" not in _imported_modules(tree)
    assert not {"remove", "unlink", "makedirs", "rename", "replace"} & _attribute_names(
        tree
    )
    # Every write-capable stream the worker opens must be either /dev/null or the
    # private protocol fd duplicated from the original stdout. No file is written.
    allowed = {("os.devnull",), ("saved",)}
    for node in _open_calls(tree):
        mode = None
        if len(node.args) >= 2:
            try:
                mode = ast.literal_eval(node.args[1])
            except (ValueError, SyntaxError):
                mode = None
        if not (isinstance(mode, str) and set(mode) & set("wax+")):
            continue
        target = ast.unparse(node.args[0])
        assert (target,) in allowed, f"worker opens {target!r} for writing"


def test_supervisor_spawns_nobody_with_runuser_and_minimal_env():
    tree = _supervisor_tree()
    source = harness.build_harness(1)
    defs = _function_defs(tree)
    assert "spawn_worker" in defs
    assert "runuser" in source
    assert '"nobody"' in source
    assert harness.RUN_AS_USER == "nobody"
    for fragment in (
        '"env", "-i"',
        "PATH=/usr/bin:/bin:/usr/local/bin",
        "HOME=/nonexistent",
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONHASHSEED=0",
        "PYTHONUNBUFFERED=1",
        "python3 -I worker.py".replace("python3 -I worker.py", "-I"),
    ):
        assert fragment in source
    assert "start_new_session=True" in source


def test_supervisor_kills_the_whole_process_group_on_timeout():
    tree = _supervisor_tree()
    assert "terminate" in _function_defs(tree)
    attributes = _attribute_names(tree)
    assert {"killpg", "getpgid", "wait"} <= attributes
    assert "kill" not in attributes, "Never kill a PID supplied by untrusted hello"
    source = harness.build_harness(1)
    assert "signal.SIGKILL" in source
    assert "TimeoutFailure" in _class_names(tree)
    assert "ProtocolFailure" in _class_names(tree)


def test_supervisor_bounds_output_and_time():
    source = harness.build_harness(1)
    tree = ast.parse(source)
    expressions = _module_expressions(tree)
    assert expressions["MAX_LINE_BYTES"] == "4 * 1024 * 1024"
    assert expressions["MAX_TOTAL_BYTES"] == "16 * 1024 * 1024"
    assert expressions["MAX_REQUEST_BYTES"] == "16 * 1024 * 1024"
    constants = _module_assignments(tree)
    assert 5.0 <= constants["STARTUP_TIMEOUT_S"] < 60.0
    assert constants["BATCH_TIMEOUT_S"] < 60.0
    assert constants["BENCH_TIMEOUT_S"] < 60.0
    assert "KISS_HARNESS_BUDGET_S" in source
    assert 'os.environ.get("KISS_HARNESS_BUDGET_S", "20")' in source
    assert "max(5.0, min(value, 60.0))" in source
    assert "select" in _imported_modules(tree)
    assert "read_line" in _attribute_names(tree)
    assert "readline" not in _attribute_names(tree)
    # writes are deadline-bounded too: a stalled candidate cannot block the supervisor
    methods = {
        node.name
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and cls.name == "WorkerChannel"
        for node in cls.body
        if isinstance(node, ast.FunctionDef)
    }
    assert {"send", "read_message", "read_line", "request"} <= methods
    send_source = source[source.index("    def send(self, payload, deadline):") :]
    assert "os.write(fd, view[:4096])" in send_source
    assert "TimeoutFailure" in send_source


def test_supervisor_drains_stderr_only_after_killing():
    source = harness.build_harness(1)
    main_source = source[source.index("def main(argv=None):") :]
    assert main_source.index("terminate(proc, worker_pid)") < main_source.index(
        "read_stderr(proc)"
    )
    assert "proc.wait(timeout=5)" in source


def test_supervisor_protection_of_trusted_paths():
    tree = _supervisor_tree()
    defs = _function_defs(tree)
    assert {
        "prepare_filesystem",
        "verify_protection",
        "write_worker",
        "set_mode",
    } <= set(defs)
    source = harness.build_harness(1)
    literals = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)}
    assert 0o444 in literals  # immutable worker script
    assert 0o755 in literals  # root-owned, traversable candidate/trusted dirs
    assert 0o555 in literals  # read-only working directory for the worker
    assert 0o644 in literals  # world readable candidate, not group writable
    assert "writable by group/other" in source
    assert "read-back does not match" in source
    assert harness.WORKER_PATH.startswith(harness.TRUSTED_DIR + "/")


def test_supervisor_only_opens_one_write_target_the_worker_tmp_file():
    tree = _supervisor_tree()
    write_targets = []
    for node in _open_calls(tree):
        if not (isinstance(node.func, ast.Name) and node.func.id == "open"):
            continue
        mode = ast.literal_eval(node.args[1]) if len(node.args) >= 2 else None
        if isinstance(mode, str) and set(mode) & set("wax+"):
            write_targets.append(node.args[0])
    assert len(write_targets) == 1
    assert isinstance(write_targets[0], ast.Name) and write_targets[0].id == "tmp_path"
    # results travel on stdout only: one JSON line, no result file write
    assert (
        "print(json.dumps(result, sort_keys=True), flush=True)"
        in harness.build_harness(1)
    )


# ---------------------------------------------------------------- trusted reference


def test_supervisor_reference_implementations():
    tree = _supervisor_tree()
    defs = _function_defs(tree)
    assert {"brute_count_pairs", "fast_count_pairs", "case_summary"} <= set(defs)

    brute = defs["brute_count_pairs"]
    nested_loops = [
        node
        for node in ast.walk(brute)
        if isinstance(node, ast.For)
        and any(isinstance(inner, ast.For) for inner in ast.walk(node))
    ]
    assert nested_loops, "brute force reference must loop over both lists"

    fast = defs["fast_count_pairs"]
    fast_calls = {
        node.func.attr
        for node in ast.walk(fast)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {"bisect_left", "bisect_right"} <= fast_calls
    assert "sorted" in _called_names(ast.Module(body=[fast], type_ignores=[]))
    assert "bisect" in _imported_modules(tree)
    assert "statistics" in _imported_modules(tree)
    assert "median" in _attribute_names(tree)


def test_references_guard_against_inverted_boundaries():
    """upper < lower must be an empty interval (0), never a negative count."""

    def has_guard(function: ast.FunctionDef) -> bool:
        for node in ast.walk(function):
            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                compared = ast.unparse(node.test)
                if "<" in compared and "upper" in compared and "lower" in compared:
                    returns_zero = any(
                        isinstance(inner, ast.Return)
                        and inner.value is not None
                        and ast.unparse(inner.value) == "0"
                        for inner in node.body
                    )
                    if returns_zero:
                        return True
        return False

    supervisor = _function_defs(_supervisor_tree())
    assert has_guard(supervisor["fast_count_pairs"])
    assert has_guard(
        _function_defs(ast.parse(harness.build_worker_source()))["baseline_count"]
    )


def test_supervisor_benchmark_methodology_is_declared():
    source = harness.build_harness(1)
    tree = ast.parse(source)
    watch = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_benchmark"
    ]
    assert watch, "run_benchmark must exist"
    for fragment in (
        "median of 3 supervisor-measured distinct-dataset repetitions",
        "copies_per_rep",
        "timed_where",
        "root_measurement",
        "overhead_wall_ms",
        "candidate_net_ms",
        "limitations",
        "digest",
        "expected_count",
    ):
        assert fragment in source, fragment
    assert "validate_bench" in _function_defs(tree)
    assert 'which="none"' in source.replace("'", '"')


def test_benchmark_dataset_generator_is_shared_by_both_sides():
    supervisor = harness.build_harness(1)
    worker = harness.build_worker_source()
    for marker in (
        "def _bench_arrays",
        "def _bench_digest",
        "6364136223846793005",
        "sha256",
    ):
        assert marker in supervisor
        assert marker in worker
    assert "hashlib" in _imported_modules(ast.parse(supervisor))
    assert "hashlib" in _imported_modules(ast.parse(worker))


def test_result_contract_keys_are_declared():
    tree = _supervisor_tree()
    assert "base_result" in _function_defs(tree)
    source = harness.build_harness(1)
    for key in (
        '"protocol_version"',
        '"status"',
        '"error_type"',
        '"phase"',
        '"tests_passed"',
        '"total"',
        '"compile_ok"',
        '"errors"',
        '"candidate_ms"',
        '"baseline_ms"',
        '"benchmark"',
        '"seed"',
        '"benchmark_n"',
        '"detail"',
    ):
        assert key in source, key
    assert "exit_code" in _function_defs(tree)


# ------------------------------------------------------------------- result parsing


def test_parse_result_accepts_a_valid_line():
    payload = _valid_result()
    parsed = harness.parse_result(json.dumps(payload) + "\n")
    assert parsed["protocol_version"] == harness.PROTOCOL_VERSION
    assert parsed["status"] == "correct"
    assert parsed["tests_passed"] == payload["tests_passed"]


def test_parse_result_reads_the_last_json_line_and_ignores_noise():
    good = json.dumps(_valid_result(status="performance_met"))
    stdout = 'harness status=...\n{"not": "a result"}\n' + good + "\n"
    parsed = harness.parse_result(stdout)
    assert parsed["status"] == "performance_met"


def test_parse_result_rejects_bad_input():
    with pytest.raises(TypeError):
        harness.parse_result(None)
    with pytest.raises(ValueError):
        harness.parse_result("no json here\n")


def test_parse_result_rejects_wrong_protocol_version():
    with pytest.raises(ValueError):
        harness.parse_result(json.dumps(_valid_result(protocol_version=2)))


def test_parse_result_rejects_unknown_status():
    with pytest.raises(ValueError):
        harness.parse_result(json.dumps(_valid_result(status="looks_great")))


def test_parse_result_enforces_counterexample_limit():
    errors = [
        {"case": {"index": i}, "expected": 0, "got": 1, "candidate_error": None}
        for i in range(3)
    ]
    with pytest.raises(ValueError):
        harness.parse_result(
            json.dumps(_valid_result(status="test_failure", errors=errors))
        )
    two = harness.parse_result(
        json.dumps(
            _valid_result(status="test_failure", errors=errors[:2], tests_passed=58)
        )
    )
    assert len(two["errors"]) == 2


def test_parse_result_rejects_bad_counter_and_types():
    # contract violations -> ValueError
    with pytest.raises(ValueError):
        harness.parse_result(json.dumps(_valid_result(tests_passed=61)))
    with pytest.raises(ValueError):
        harness.parse_result(json.dumps(_valid_result(benchmark={"n": 1})))
    # wrong field types -> TypeError
    with pytest.raises(TypeError):
        harness.parse_result(json.dumps(_valid_result(tests_passed=True)))
    with pytest.raises(TypeError):
        harness.parse_result(json.dumps(_valid_result(errors="none")))
    with pytest.raises(TypeError):
        harness.parse_result(json.dumps(_valid_result(candidate_ms="fast")))
    with pytest.raises(TypeError):
        harness.parse_result(json.dumps(_valid_result(benchmark=[1, 2, 3])))


def test_parse_result_accepts_null_measurements_for_failure_statuses():
    parsed = harness.parse_result(
        json.dumps(
            _valid_result(
                status="compilation_error",
                tests_passed=0,
                candidate_ms=None,
                baseline_ms=None,
                benchmark=None,
                compile_ok=False,
            )
        )
    )
    assert parsed["candidate_ms"] is None
    assert parsed["status"] == "compilation_error"


def test_result_field_types_helper_matches_documented_keys():
    types = harness.result_field_types()
    assert types["protocol_version"] is int
    assert types["status"] is str
    assert types["errors"] is list
    assert types["candidate_ms"] == (int, float, type(None))
