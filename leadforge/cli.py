"""LEADFORGE command-line interface.

Subcommands map 1:1 to engine operations so an AI agent can drive the CRM over
MCP with the same verbs a human uses. Every command emits JSON by default and
supports --format table for human reading. Failures exit non-zero.

Note: --format / --db are global flags and must precede the subcommand.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Any, List, Optional

from .core import Engine, LeadForgeError, STAGES, TOOL_NAME, TOOL_VERSION


def _emit(payload: Any, fmt: str) -> None:
    if fmt == "json":
        print(json.dumps(payload, indent=2))
        return
    # table
    if isinstance(payload, dict) and "by_stage" in payload:
        print(f"Leads: {payload['total_leads']}  Open: ${payload['open_value']:,.2f}  "
              f"Won: ${payload['won_value']:,.2f}  Win-rate: {payload['win_rate']:.1%}")
        for stage in STAGES:
            s = payload["by_stage"][stage]
            print(f"  {stage:<10} {s['count']:>3} leads   ${s['value']:>12,.2f}")
        return
    rows = payload if isinstance(payload, list) else [payload]
    if not rows:
        print("(none)")
        return
    if all(isinstance(r, dict) and "stage" in r for r in rows):
        print(f"{'ID':<10}{'NAME':<20}{'STAGE':<11}{'VALUE':>12}  EMAIL")
        for r in rows:
            print(f"{r['id']:<10}{r['name'][:19]:<20}{r['stage']:<11}"
                  f"{r['value']:>12,.2f}  {r['email']}")
    elif all(isinstance(r, dict) and "subject" in r for r in rows):
        for r in rows:
            print(f"[{r['due']}] {r['email']} -> step {r['step']}: {r['subject']}")
    else:
        print(json.dumps(rows, indent=2))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=TOOL_NAME,
                                description="MCP-native CRM pipeline with email sequences")
    p.add_argument("--version", action="version",
                   version=f"{TOOL_NAME} {TOOL_VERSION}")
    p.add_argument("--format", choices=["table", "json"], default="json")
    p.add_argument("--db", help="path to JSON store (or env LEADFORGE_DB)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="add a lead")
    a.add_argument("name")
    a.add_argument("email")
    a.add_argument("--company", default="")
    a.add_argument("--value", type=float, default=0.0)

    ls = sub.add_parser("list", help="list leads")
    ls.add_argument("--stage", choices=STAGES)

    mv = sub.add_parser("move", help="move a lead to a stage")
    mv.add_argument("lead_id")
    mv.add_argument("stage", choices=STAGES)

    en = sub.add_parser("enroll", help="enroll a lead in an email sequence")
    en.add_argument("lead_id")
    en.add_argument("--sequence", default="cold-outreach")

    sub.add_parser("due", help="show sequence steps that are due now")
    sub.add_parser("send", help="mark all due steps as sent and advance them")
    sub.add_parser("pipeline", help="pipeline summary metrics")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        eng = Engine(path=args.db)
        mutating = True
        if args.cmd == "add":
            out: Any = asdict(eng.add_lead(args.name, args.email,
                                           args.company, args.value))
        elif args.cmd == "list":
            out = eng.list_leads(args.stage)
            mutating = False
        elif args.cmd == "move":
            out = asdict(eng.move(args.lead_id, args.stage))
        elif args.cmd == "enroll":
            out = asdict(eng.enroll(args.lead_id, args.sequence))
        elif args.cmd == "due":
            out = eng.due_steps()
            mutating = False
        elif args.cmd == "send":
            out = eng.send_due()
        elif args.cmd == "pipeline":
            out = eng.pipeline()
            mutating = False
        else:  # pragma: no cover
            raise LeadForgeError(f"unknown command: {args.cmd}")
        if mutating:
            eng.save()
        _emit(out, args.format)
        return 0
    except LeadForgeError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover — safety net for unexpected failures
        print(json.dumps({"error": f"unexpected error: {exc}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
