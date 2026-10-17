"""Bounded official-SDK adapter and append-only evidence. No host execution of candidates."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import signal
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from createos import (
    Client,
    CreateSandboxRequest,
    ExecOptions,
    ForkSandboxRequest,
    ListSandboxesOptions,
    RetryOptions,
    RunCommandRequest,
)
from dotenv import dotenv_values


def utcnow():
    return datetime.now(UTC).isoformat()


def load_secrets():
    local = dotenv_values(Path.cwd() / ".env")
    mercury_file = os.environ.get("MERCURY_ENV_FILE") or local.get("MERCURY_ENV_FILE")
    mercury = dotenv_values(Path(mercury_file).expanduser()) if mercury_file else {}

    def pick(*names):
        return next(
            (
                os.environ.get(n) or local.get(n) or mercury.get(n)
                for n in names
                if os.environ.get(n) or local.get(n) or mercury.get(n)
            ),
            None,
        )

    key = pick("CREATEOS_API_KEY", "CREATEOS_PROJECT_API_KEY", "CREATEOS_PLAN_API_KEY")
    modelkey = pick("MERCURY_API_KEY", "INCEPTION_API_KEY")
    if not key or not modelkey:
        raise RuntimeError(
            "Missing credential: CREATEOS or MERCURY (values never logged)"
        )
    return {"createos": key, "mercury": modelkey}


@contextmanager
def deadline(seconds):
    if seconds <= 0:
        raise TimeoutError("Operation deadline exhausted")
    old_handler = signal.getsignal(signal.SIGALRM)
    current_remaining, _ = signal.getitimer(signal.ITIMER_REAL)
    effective = min(seconds, current_remaining) if current_remaining > 0 else seconds

    def expired(*_):
        raise TimeoutError(f"Orchestrator deadline ({seconds}s)")

    signal.signal(signal.SIGALRM, expired)
    old_timer = signal.setitimer(signal.ITIMER_REAL, effective)
    start = time.monotonic()
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old_handler)
        if old_timer[0]:
            signal.setitimer(
                signal.ITIMER_REAL,
                max(0.001, old_timer[0] - (time.monotonic() - start)),
                old_timer[1],
            )


class Ledger:
    def __init__(self, kind="search", root=None):
        self.run_id = f"{kind}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}-{os.urandom(3).hex()}"
        self.path = Path(root or "runs") / self.run_id
        self.path.mkdir(parents=True, exist_ok=False, mode=0o700)
        self.secrets = []

    def clean(self, value):
        text = json.dumps(value, default=str)
        for secret in self.secrets:
            if secret:
                text = text.replace(secret, "[REDACTED]")
        return json.loads(text)

    def event(self, event, **fields):
        row = self.clean(
            {"timestamp": utcnow(), "run_id": self.run_id, "event": event, **fields}
        )
        with (self.path / "events.jsonl").open("a") as out:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            out.flush()
        return row

    def artifact(self, filename, data):
        target = self.path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            for secret in self.secrets:
                data = data.replace(secret, "[REDACTED]")
            content = data
        else:
            content = json.dumps(self.clean(data), indent=2, ensure_ascii=False)
        tmp = target.with_name(f".{target.name}.{os.urandom(4).hex()}.tmp")
        tmp.write_text(content)
        os.replace(tmp, target)


def projection(box):
    d = dataclasses.asdict(box.data)
    return {
        k: (v.value if hasattr(v, "value") else v)
        for k, v in d.items()
        if k
        in {
            "id",
            "name",
            "status",
            "forked_from",
            "egress_rules",
            "ingress_enabled",
            "shape",
            "rootfs",
            "created_at",
        }
    }


def checked(adapter, box, command, args=None, timeout=40):
    result = adapter.exec(box, command, args, timeout=timeout)
    if result.get("exit_code") != 0:
        raise RuntimeError(f"Remote command failed: {result}")
    return result["standard_output"]


class Sandboxes:
    def __init__(self, key, ledger, max_created=8, op_timeout=60):
        self.client = Client(api_key=key, timeout=20, retry=RetryOptions(max_retries=0))
        self.ledger = ledger
        self.owned = {}
        self.max_created = max_created
        self.attempts = 0
        self.op_timeout = op_timeout
        self.rules = ["pypi.org:443", "*.pythonhosted.org:443"]
        with deadline(25):
            self.initial_ids = {
                b.id
                for b in self.client.list_sandboxes(ListSandboxesOptions(limit=500))
            }
        self.ledger.event("inventory_initial", sandbox_ids=sorted(self.initial_ids))

    def op(self, name, fn, timeout=None, **fields):
        started = time.monotonic()
        try:
            with deadline(timeout or self.op_timeout):
                result = fn()
            self.ledger.event(
                name, duration_ms=(time.monotonic() - started) * 1000, **fields
            )
            return result
        except Exception as exc:
            self.ledger.event(
                name + "_error",
                duration_ms=(time.monotonic() - started) * 1000,
                error_type=type(exc).__name__,
                error=str(exc),
                **fields,
            )
            raise

    def wait(self, box, state, seconds=75):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.op(
                "get",
                box.refresh,
                timeout=min(20, max(0.01, end - time.monotonic())),
                sandbox_id=box.id,
            )
            actual = (
                box.status.value if hasattr(box.status, "value") else str(box.status)
            )
            self.ledger.event("state", **projection(box))
            if actual == state:
                return box
            if actual in {"error", "failed", "destroyed"}:
                raise RuntimeError(f"{box.id} reached {actual}, expected {state}")
            time.sleep(min(1, max(0, end - time.monotonic())))
        raise TimeoutError(f"{box.id}: waiting for {state}")

    def reserve(self):
        if self.attempts >= self.max_created:
            raise RuntimeError("max_sandboxes creation limit reached")
        self.attempts += 1

    def reconcile(self, name=None, parent=None):
        inventory = self.op(
            "reconcile",
            lambda: self.client.list_sandboxes(ListSandboxesOptions(limit=500)),
            timeout=25,
        )
        for box in inventory:
            d = projection(box)
            if box.id not in self.initial_ids and (
                (name and d.get("name") == name)
                or (parent and d.get("forked_from") == parent)
            ):
                self.owned[box.id] = box
                self.ledger.event("resource_reconciled", **d)
        self.ledger.event(
            "inventory_reconciled", observed_ids=[b.id for b in inventory]
        )

    def create(self):
        self.reserve()
        name = ("kiss-" + self.ledger.run_id[-17:]).lower()
        try:
            box = self.op(
                "create",
                lambda: self.client.create_sandbox(
                    CreateSandboxRequest(
                        name=name,
                        shape="s-1vcpu-1gb",
                        rootfs="devbox:1",
                        ingress_enabled=False,
                        egress_rules=self.rules,
                        environment_variables={},
                        auto_pause_after_seconds=120,
                    )
                ),
            )
        except Exception:
            self.reconcile(name=name)
            raise
        self.owned[box.id] = box
        self.ledger.event("resource_created", **projection(box))
        return self.wait(box, "running")

    def pause(self, box):
        box.refresh()
        if str(getattr(box.status, "value", box.status)) != "paused":
            self.op("pause", box.pause, sandbox_id=box.id)
        return self.wait(box, "paused")

    def resume(self, box):
        box.refresh()
        if str(getattr(box.status, "value", box.status)) != "running":
            self.op("resume", box.resume, sandbox_id=box.id)
        return self.wait(box, "running")

    def fork(self, parent):
        self.wait(parent, "paused", seconds=10)
        self.reserve()
        try:
            box = self.op(
                "fork",
                lambda: parent.fork(
                    ForkSandboxRequest(
                        start_paused=False,
                        ingress_enabled=False,
                        egress_rules=self.rules,
                    )
                ),
                parent_sandbox_id=parent.id,
            )
        except Exception:
            self.reconcile(parent=parent.id)
            raise
        self.owned[box.id] = box
        self.wait(box, "running")
        d = projection(box)
        self.ledger.event("resource_forked", **d)
        if d.get("forked_from") != parent.id:
            raise RuntimeError("Physical fork ancestry not confirmed by server")
        return box

    def upload(self, box, path, text):
        self.op(
            "upload",
            lambda: box.files.upload(path, text.encode()),
            sandbox_id=box.id,
            path=path,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
        )

    def exec(self, box, command, arguments=None, timeout=45):
        response = self.op(
            "exec",
            lambda: box.run_command(
                RunCommandRequest(command=command, arguments=arguments or []),
                ExecOptions(timeout=timeout, disable_retry=True),
            ),
            timeout=timeout + 3,
            sandbox_id=box.id,
        )
        r = dataclasses.asdict(response.result)
        for key in ("stdout", "stderr", "standard_output", "standard_error"):
            if len(r.get(key) or "") > 100000:
                r[key] = r[key][:100000]
                r["output_truncated"] = True
        self.ledger.event("exec_result", sandbox_id=box.id, **r)
        return r

    def destroy(self, box):
        if box.id not in self.owned:
            raise RuntimeError("Refusing cleanup outside owned IDs")
        self.op("cleanup_get", box.refresh, timeout=20, sandbox_id=box.id)
        state = str(getattr(box.status, "value", box.status))
        if state == "destroyed":
            self.ledger.event("cleanup_verified", **projection(box))
            return
        if state == "paused":
            # Observed paused-destroy transitions can remain destroying; use supported resume first.
            self.resume(box)
        if state != "destroying":
            self.op("destroy", box.destroy, timeout=25, sandbox_id=box.id)
        self.wait(box, "destroyed", seconds=45)
        self.ledger.event("cleanup_verified", **projection(box))

    def cleanup(self, budget_seconds=360):
        cleanup_end = time.monotonic() + budget_seconds
        run_name = ("kiss-" + self.ledger.run_id[-17:]).lower()
        try:
            rem = cleanup_end - time.monotonic()
            if rem > 0:
                inventory = self.op(
                    "cleanup_reconcile",
                    lambda: self.client.list_sandboxes(ListSandboxesOptions(limit=500)),
                    timeout=min(25, rem),
                )
                progressed = True
                while progressed:
                    progressed = False
                    for box in inventory:
                        if box.id in self.initial_ids or box.id in self.owned:
                            continue
                        d = projection(box)
                        if (
                            d.get("name") == run_name
                            or d.get("forked_from") in self.owned
                        ):
                            self.owned[box.id] = box
                            self.ledger.event("resource_reconciled", **d)
                            progressed = True
        except Exception as exc:  # noqa: BLE001 - continue cleaning known owned resources
            self.ledger.event(
                "cleanup_reconcile_warning",
                error_type=type(exc).__name__,
                error=str(exc),
            )
        results = []
        for box in reversed(list(self.owned.values())):
            rem = cleanup_end - time.monotonic()
            if rem <= 0:
                results.append(
                    {
                        "sandbox_id": box.id,
                        "status": "cleanup_pending",
                        "error": "Cleanup time budget exhausted",
                    }
                )
                continue
            try:
                with deadline(rem):
                    self.destroy(box)
                results.append(
                    {"sandbox_id": box.id, "status": "destroyed", "verified": True}
                )
            except Exception as exc:  # noqa: BLE001 - record failure and always clean owned resources
                timed_out = (
                    isinstance(exc, TimeoutError) and time.monotonic() >= cleanup_end
                )
                results.append(
                    {
                        "sandbox_id": box.id,
                        "status": "cleanup_pending" if timed_out else "cleanup_error",
                        "error": str(exc),
                    }
                )
        self.ledger.artifact("cleanup.json", results)
        self.client.close()
        return results
