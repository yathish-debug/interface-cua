import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse, os
from cua.artifact.recorder import build


def _params(pairs: list[str]) -> dict:
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="evidence/run_... dir")
    ap.add_argument("--capability-id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--app-id", required=True)
    ap.add_argument("--entry-url", required=True)
    ap.add_argument("--param", action="append", default=[], help="name=literal (repeatable)")
    ap.add_argument("--success-text", required=True, help="stable label proving success")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    cap = build(a.run, a.capability_id, a.title, a.app_id, a.entry_url,
                _params(a.param), a.success_text)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w") as f:
        f.write(cap.model_dump_json(indent=2))
    print(f"Wrote {a.out}  (schema {cap.schema_version}, {len(cap.steps)} steps, status={cap.status})")


if __name__ == "__main__":
    main()