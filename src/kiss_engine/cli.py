"""Project CLI: no shell-generated solutions execute locally."""

import argparse
from dataclasses import fields

from .engine import Limits, run_search


def main():
    p = argparse.ArgumentParser(
        prog="kiss",
        description="Evidence-first code search. Local only, real CreateOS forks, Mercury direct.",
    )
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "failures", help="Explicit remote failure fixtures, never attributed to Mercury"
    )
    sub.add_parser(
        "smoke",
        help="Real fork inheritance/independence, two-child running and egress probe",
    )
    sub.add_parser(
        "audit", help="Read back only this project recorded resource IDs; no mutations"
    )
    run = sub.add_parser("run", help="Bounded real Mercury/CreateOS T1b search")
    run.add_argument("--task", choices=["count_pairs"], default="count_pairs")
    for f in fields(Limits):
        option = "--" + f.name.replace("_", "-")
        if f.name == "stop_on_target":
            run.add_argument(option, action="store_true", default=f.default)
        else:
            run.add_argument(option, type=int, default=f.default)
    serve = sub.add_parser(
        "serve", help="Loopback dashboard with bounded run initiation"
    )
    serve.add_argument("--port", type=int, default=8097)
    args = p.parse_args()
    if args.command == "audit":
        from .audit import audit

        result = audit()
        raise SystemExit(1 if result["unresolved"] else 0)
    if args.command == "failures":
        from .failures import failures

        raise SystemExit(0 if failures()["ok"] else 1)
    if args.command == "smoke":
        from .smoke import smoke

        raise SystemExit(0 if smoke()["ok"] else 1)
    if args.command == "run":
        config = {f.name: getattr(args, f.name) for f in fields(Limits)}
        result = run_search(Limits(**config))
        raise SystemExit(0 if result["status"] == "completed" else 1)
    if args.command == "serve":
        from .web import serve

        serve(args.port)


if __name__ == "__main__":
    main()
