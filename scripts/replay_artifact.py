import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import argparse, json
from cua.replay.engine import replay


def _params(pairs):
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", required=True)
    ap.add_argument("--param", action="append", default=[], help="name=value (repeatable)")
    ap.add_argument("--headed", action="store_true", help="show the browser")
    ap.add_argument("--policy", default="config/policy.json", help="path to policy config")
    a = ap.parse_args()

    r = replay(a.artifact, _params(a.param), headed=a.headed, policy_path=a.policy)
    print("=" * 50)
    print(f"OUTCOME:  {r.outcome.value}")
    if r.outcome.value == "success":
        print(f"OUTPUTS:  {json.dumps(r.outputs, indent=2)}")
    elif r.outcome.value == "business_outcome":
        print(f"CODE:     {r.business_code}")
        print(f"MESSAGE:  {r.business_message}")
    else:
        print(f"STEP:     {r.failed_step_index}")
        print(f"EXPECTED: {r.expected}")
        print(f"OBSERVED: {r.observed}")
        print(f"ERROR:    {r.error}")
    if r.recoveries:
        print(f"RECOVERED: {r.recoveries}")
    print(f"STEPS:    {r.steps_attempted}")
    print(f"EVIDENCE: {r.evidence_dir}")
    print("=" * 50)
    with open(os.path.join(r.evidence_dir, "result.json"), "w") as f:
        f.write(r.model_dump_json(indent=2))


if __name__ == "__main__":
    main()