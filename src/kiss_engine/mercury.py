"""Direct Inception Mercury structured generation; explicit bounded retries, no fallback."""

from __future__ import annotations

import ast
import hashlib
import json
import time

import httpx

from .runtime import deadline

TASK = """Implement count_pairs(a: list[int], b: list[int], lower: int, upper: int) -> int.
Return number of index pairs (i,j) such that lower <= a[i]+b[j] <= upper, inclusive.
Lists are independent (not pairs within one list). Duplicates count by indices.
Empty inputs yield zero. If lower > upper return zero. Values up to +/-10**9; bounds up to +/-2*10**9.
At most 10**6 items per list; inputs need not be sorted. Do not mutate caller inputs.
Python 3, standard library only. Complete self-contained module; expose count_pairs.
The evaluator tests exact correctness and measures comparable benchmark wall time against a sort/bisect reference.
Prioritize correctness before speed. No I/O, network, subprocess, filesystem, eval or exec; no benchmark detection.
You do not receive the hidden test suite. Return JSON with approach, code, explanation, and nothing else.
"""
APPROACHES = [
    (
        "sorted-bisect",
        "Sort one list; use binary searches for each value in the other. Handle duplicates and inclusive bounds.",
    ),
    (
        "two-pointer",
        "Sort both lists and derive a pair-count-at-most routine using two pointers; subtract two thresholds. Explore this distinct algorithm.",
    ),
]
SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in ("approach", "code", "explanation")},
    "required": ["approach", "code", "explanation"],
    "additionalProperties": False,
}


class GenerationError(RuntimeError):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


def validate_code(data):
    if not isinstance(data, dict) or not all(
        isinstance(data.get(k), str) for k in ("approach", "code", "explanation")
    ):
        raise GenerationError(
            "invalid_generation", "Output does not match complete-code contract"
        )
    code = data["code"]
    if not code.strip():
        raise GenerationError("empty_generation", "Empty code")
    if len(code.encode()) > 40000:
        raise GenerationError("invalid_generation", "Code exceeds 40KB limit")
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise GenerationError("compilation_error", str(exc)) from exc
    defs = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name == "count_pairs"
    ]
    if len(defs) != 1 or len(defs[0].args.args) != 4:
        raise GenerationError(
            "invalid_generation",
            "Missing count_pairs with exactly four positional arguments",
        )
    # A restricted task contract reduces obvious abuse, not a proof of safety.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            n.name.split(".")[0]
            not in {
                "bisect",
                "collections",
                "itertools",
                "math",
                "typing",
                "functools",
                "array",
            }
            for n in node.names
        ):
            raise GenerationError(
                "invalid_generation",
                "Import outside declared standard-library task allowlist",
            )
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[
            0
        ] not in {
            "bisect",
            "collections",
            "itertools",
            "math",
            "typing",
            "functools",
            "array",
            "__future__",
        }:
            raise GenerationError(
                "invalid_generation", "Import outside declared task allowlist"
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id
            in {"exec", "eval", "open", "compile", "__import__", "input", "breakpoint"}
        ):
            raise GenerationError(
                "invalid_generation", "Forbidden dynamic execution/I/O"
            )
    return code


class Mercury:
    def __init__(self, key, ledger, max_calls=5, client=None, sleeper=time.sleep):
        self.client = client or httpx.Client(
            base_url="https://api.inceptionlabs.ai/v1/",
            timeout=httpx.Timeout(30, connect=10),
        )
        self.key, self.ledger, self.max_calls = key, ledger, max_calls
        self.calls = 0
        self.sleeper = sleeper

    def generate(self, candidate_id, approach, parent=None):
        instruction = dict(APPROACHES).get(approach, approach)
        prompt = TASK + "\nRequested approach: " + approach + " — " + instruction
        if parent:
            prompt += (
                "\nRevise YOUR parent solution. Correctness first, then optimize; explain changes. Parent code:\n"
                + parent["code"]
                + "\nMeasured feedback from this parent only:\n"
                + json.dumps(parent["feedback"])
            )
        messages = [
            {
                "role": "system",
                "content": "You are a code-search candidate generator. Follow the exact task contract and requested approach; return complete code in JSON.",
            },
            {"role": "user", "content": prompt},
        ]
        payload = {
            "model": "mercury-2.5",
            "reasoning_effort": "instant",
            "temperature": 0.75,
            "max_completion_tokens": 2500,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "solution", "strict": True, "schema": SCHEMA},
            },
        }
        self.ledger.artifact(f"candidates/{candidate_id}/prompt.json", payload)
        for attempt in range(3):
            if self.calls >= self.max_calls:
                raise GenerationError(
                    "call_limit", "Configured max_model_calls reached"
                )
            self.calls += 1
            self.ledger.artifact(
                f"candidates/{candidate_id}/prompt-attempt-{attempt + 1}.json", payload
            )
            started = time.monotonic()
            try:
                with deadline(40):
                    response = self.client.post(
                        "chat/completions",
                        headers={"Authorization": "Bearer " + self.key},
                        json=payload,
                    )
            except (httpx.HTTPError, TimeoutError) as exc:
                self.ledger.event(
                    "generation_error",
                    candidate_id=candidate_id,
                    status="api_error",
                    error_type=type(exc).__name__,
                    duration_ms=(time.monotonic() - started) * 1000,
                )
                raise GenerationError(
                    "api_error", "Inception request failed: " + type(exc).__name__
                ) from exc
            elapsed = (time.monotonic() - started) * 1000
            self.ledger.event(
                "generation_http",
                candidate_id=candidate_id,
                http_status=response.status_code,
                duration_ms=elapsed,
                attempt=attempt + 1,
                model="mercury-2.5",
                provider="Inception direct",
            )
            if response.status_code == 429:
                if attempt < 2 and self.calls < self.max_calls:
                    self.sleeper(min(4, 2**attempt))
                    continue
                raise GenerationError("api_error", "HTTP 429 retry budget exhausted")
            if response.status_code != 200:
                raise GenerationError(
                    "api_error", f"Inception HTTP {response.status_code}; no fallback"
                )
            if len(response.content) > 1000000:
                raise GenerationError(
                    "invalid_generation", "Provider response exceeds bounded payload"
                )
            try:
                raw = response.json()
            except ValueError as exc:
                raise GenerationError(
                    "invalid_generation", "Provider returned invalid JSON"
                ) from exc
            if not isinstance(raw, dict):
                raise GenerationError(
                    "invalid_generation", "Provider envelope must be an object"
                )
            if raw.get("model") not in {None, "mercury-2.5"}:
                raise GenerationError(
                    "api_error", "Unexpected provider model; no substitution allowed"
                )
            self.ledger.artifact(
                f"candidates/{candidate_id}/response-attempt-{attempt + 1}.json", raw
            )
            self.ledger.artifact(f"candidates/{candidate_id}/response.json", raw)
            self.ledger.event(
                "generation_usage",
                candidate_id=candidate_id,
                usage=raw.get("usage"),
                warnings=raw.get("warning", raw.get("warnings")),
                cost_note="Only provider-returned cost, if present; no inferred charge",
            )
            choices = raw.get("choices") or []
            if not choices:
                raise GenerationError(
                    "empty_generation", "Provider returned no choices"
                )
            if not isinstance(choices, list) or not isinstance(choices[0], dict):
                raise GenerationError("invalid_generation", "Malformed choice envelope")
            choice = choices[0]
            if choice.get("finish_reason") == "length":
                self.ledger.event(
                    "generation_truncated",
                    candidate_id=candidate_id,
                    attempt=attempt + 1,
                )
                if attempt < 2 and self.calls < self.max_calls:
                    payload["max_completion_tokens"] = min(
                        6000, payload["max_completion_tokens"] * 2
                    )
                    continue
                raise GenerationError(
                    "truncated_generation", "Provider token limit reached"
                )
            if not isinstance(choice.get("message"), dict):
                raise GenerationError(
                    "invalid_generation", "Malformed message envelope"
                )
            text = choice["message"].get("content")
            if not isinstance(text, str) or not text.strip():
                raise GenerationError("empty_generation", "Provider returned no text")
            try:
                try:
                    result = json.loads(text)
                except ValueError as exc:
                    raise GenerationError(
                        "invalid_generation", "Structured content is not JSON"
                    ) from exc
                code = validate_code(result)
            except GenerationError as exc:
                self.ledger.event(
                    "generation_validation_error",
                    candidate_id=candidate_id,
                    status=exc.status,
                    detail=str(exc),
                    attempt=attempt + 1,
                )
                if (
                    exc.status in {"invalid_generation", "empty_generation"}
                    and attempt < 2
                    and self.calls < self.max_calls
                ):
                    payload["messages"] = messages + [
                        {
                            "role": "user",
                            "content": "Previous response violated the output contract. Return exactly one JSON OBJECT with string keys approach, code, explanation. code must contain the COMPLETE Python module with count_pairs(a,b,lower,upper). No lists, metadata, or markdown. Keep the implementation concise.",
                        }
                    ]
                    continue
                raise
            result.update(
                generation_ms=elapsed,
                code_sha256=hashlib.sha256(code.encode()).hexdigest(),
                provider="Inception direct",
                model=raw.get("model", "mercury-2.5"),
            )
            self.ledger.artifact(f"candidates/{candidate_id}/solution.py", code)
            self.ledger.event(
                "generation_completed",
                candidate_id=candidate_id,
                approach=result["approach"],
                code_sha256=result["code_sha256"],
                generation_ms=elapsed,
            )
            return result
        raise GenerationError("api_error", "Retry budget exhausted")

    def close(self):
        self.client.close()
