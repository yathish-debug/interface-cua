"""Print one replay run's audit and control history in a readable format."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []

    rows = []

    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))

    return rows


def short_time(timestamp: str) -> str:
    if not timestamp:
        return "-"

    return timestamp.replace("T", " ").split("+")[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        required=True,
        help="Evidence directory, for example evidence/replay_20260918_170311",
    )
    args = parser.parse_args()

    run_dir = Path(args.run)

    if not run_dir.is_dir():
        raise SystemExit(f"Run directory not found: {run_dir}")

    audit_rows = read_jsonl(run_dir / "audit.jsonl")
    control_rows = read_jsonl(run_dir / "control.jsonl")

    print("\n" + "=" * 72)
    print(f"RUN: {run_dir.name}")
    print("=" * 72)

    print("\nAUDIT TRAIL")
    if not audit_rows:
        print("  No audit events found.")
    else:
        for row in audit_rows:
            time = short_time(row.get("ts", ""))
            actor = row.get("actor", "-")
            event = row.get("event_type", "-")
            action = row.get("action")
            decision = row.get("decision")
            detail = row.get("detail")

            message = f"  {time} | {actor:10} | {event}"

            if action:
                message += f" | action={action}"

            if decision:
                message += f" | decision={decision}"

            if detail:
                message += f" | {detail}"

            print(message)

    print("\nCONTROL HANDOFF")
    if not control_rows:
        print("  No human handoff occurred. Automation kept control.")
    else:
        for row in control_rows:
            time = short_time(row.get("ts", ""))
            from_state = row.get("from_state", "-")
            to_state = row.get("to_state", "-")
            controller = row.get("controller", "-")
            reason = row.get("reason", "-")

            print(
                f"  {time} | {from_state:10} → {to_state:10} "
                f"| controller={controller:5} | {reason}"
            )

    print("\nFILES")
    print(f"  Audit:   {run_dir / 'audit.jsonl'}")
    print(f"  Control: {run_dir / 'control.jsonl'}")
    print("=" * 72)


if __name__ == "__main__":
    main()