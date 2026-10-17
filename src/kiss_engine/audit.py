"""Read-only reconciliation of IDs recorded as created/forked by THIS repository."""

import json

from createos import Client, RetryOptions

from .runtime import Ledger, deadline, load_secrets, projection


def recorded_resources(root):
    owned = {}
    usage = []
    for file in sorted(root.glob("*/events.jsonl")):
        for line in file.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("event") in {
                "resource_created",
                "resource_forked",
                "resource_reconciled",
            } and row.get("id"):
                owned.setdefault(row["id"], set()).add(file.parent.name)
            if row.get("event") == "generation_usage":
                usage.append(
                    {
                        "run_id": file.parent.name,
                        "candidate_id": row.get("candidate_id"),
                        "usage": row.get("usage"),
                    }
                )
    return owned, usage


def audit():
    ledger = Ledger("audit")
    secrets = load_secrets()
    ledger.secrets = list(secrets.values())
    owned, usage = recorded_resources(ledger.path.parent)
    states = []
    with (
        Client(
            api_key=secrets["createos"], timeout=10, retry=RetryOptions(max_retries=0)
        ) as client,
        deadline(180),
    ):
        for id, runs in sorted(owned.items()):
            try:
                with deadline(12):
                    box = client.get_sandbox(id)
                row = projection(box) | {"owner_runs": sorted(runs)}
            except Exception as exc:  # noqa: BLE001 - report unresolved resource without altering it
                row = {
                    "id": id,
                    "status": "unresolved",
                    "owner_runs": sorted(runs),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            states.append(row)
            ledger.event("resource_readback", **row)
    tokens = {
        k: sum(
            u["usage"].get(k, 0)
            for u in usage
            if isinstance(u.get("usage"), dict)
            and isinstance(u["usage"].get(k, 0), int)
        )
        for k in ["prompt_tokens", "completion_tokens", "total_tokens"]
    }
    result = {
        "run_id": ledger.run_id,
        "resources": states,
        "owned_count": len(states),
        "destroyed_count": sum(r["status"] == "destroyed" for r in states),
        "unresolved": [r for r in states if r["status"] != "destroyed"],
        "usage_events": len(usage),
        "provider_reported_tokens": tokens,
        "cost": "Not inferred: account credits/currency usage unavailable in these responses.",
        "model_usage_records": usage,
        "read_only": True,
    }
    ledger.artifact("summary.json", result)
    print(
        json.dumps(
            {
                k: v
                for k, v in result.items()
                if k not in {"resources", "model_usage_records"}
            },
            indent=2,
        )
    )
    return result
