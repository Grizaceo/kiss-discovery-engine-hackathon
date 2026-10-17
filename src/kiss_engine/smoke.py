"""Real integration smoke. All resources tagged by this run and cleaned in finally."""

import json

from .runtime import Ledger, Sandboxes, deadline, load_secrets, projection


def checked(adapter, box, command, args=None, timeout=40):
    result = adapter.exec(box, command, args, timeout=timeout)
    if result.get("exit_code") != 0:
        raise RuntimeError(f"Remote command failed: {result}")
    return result["standard_output"]


def smoke():
    ledger = Ledger("smoke")
    secrets = load_secrets()
    ledger.secrets = list(secrets.values())
    ledger.event(
        "run_started",
        purpose="fork inheritance, independence, two-child running concurrency, egress probe",
        cost="not observable; no invented estimate",
        max_sandboxes=3,
    )
    adapter = Sandboxes(secrets["createos"], ledger, max_created=3)
    result = {"run_id": ledger.run_id, "path": str(ledger.path), "ok": False}
    try:
        with deadline(480):
            base = adapter.create()
            checked(
                adapter,
                base,
                "sh",
                [
                    "-c",
                    "mkdir -p /workspace; printf base-marker > /workspace/marker.txt; python3 --version; command -v runuser; id",
                ],
            )
            adapter.pause(base)
            child1 = adapter.fork(base)
            inherited = checked(
                adapter, child1, "cat", ["/workspace/marker.txt"]
            ).strip()
            assert inherited == "base-marker", inherited
            checked(
                adapter,
                child1,
                "sh",
                ["-c", "printf child-marker > /workspace/marker.txt"],
            )
            assert (
                checked(adapter, child1, "cat", ["/workspace/marker.txt"]).strip()
                == "child-marker"
            )
            adapter.pause(child1)
            adapter.resume(base)
            parent_after = checked(
                adapter, base, "cat", ["/workspace/marker.txt"]
            ).strip()
            assert parent_after == "base-marker", parent_after
            adapter.pause(base)
            child2 = adapter.fork(base)
            adapter.resume(child1)
            adapter.wait(child1, "running")
            adapter.wait(child2, "running")
            concurrent = [projection(child1), projection(child2)]
            # Both guests are observed running while the base is paused.
            ledger.event(
                "two_children_running", children=concurrent, base=projection(base)
            )
            assert (
                checked(adapter, child2, "cat", ["/workspace/marker.txt"]).strip()
                == "base-marker"
            )
            probe = checked(
                adapter,
                child2,
                "python3",
                [
                    "-c",
                    "import urllib.request,json; out={};\nfor url in ['https://pypi.org/simple/','https://example.com/']:\n try:\n  r=urllib.request.urlopen(url,timeout=6);out[url]={'reachable':True,'status':r.status}\n except Exception as e: out[url]={'reachable':False,'error_type':type(e).__name__}\nprint(json.dumps(out))",
                ],
                timeout=20,
            )
            network = json.loads(probe)
            ledger.event(
                "egress_probe",
                results=network,
                configured_rules=adapter.rules,
                note="No deny-all claim; allowlisted package hosts only. Hostname probe is empirical, not complete network audit.",
            )
            result.update(
                ok=True,
                base_id=base.id,
                child_ids=[child1.id, child2.id],
                inheritance_verified=True,
                independence_verified=True,
                concurrent_running_observed=2,
                egress=network,
            )
            ledger.event("smoke_passed", **result)
    except Exception as exc:  # noqa: BLE001 - record failure and always clean owned resources
        result["error"] = str(exc)
        ledger.event("run_error", error_type=type(exc).__name__, error=str(exc))
    finally:
        result["cleanup"] = adapter.cleanup()
        result["ok"] = result["ok"] and all(
            r["status"] == "destroyed" for r in result["cleanup"]
        )
        ledger.artifact("summary.json", result)
        print(json.dumps(ledger.clean(result), indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(0 if smoke()["ok"] else 1)
