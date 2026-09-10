import argparse, json, os, sys

# Make `cua` importable when run as a plain script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from cua.surface.web import WebSurface
from cua.agent.loop import run_goal

load_dotenv()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--goal", required=True)
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--max-steps", type=int, default=15)
    p.add_argument("--headed", action="store_true", default=True)
    args = p.parse_args()

    surface = WebSurface(args.url, headed=args.headed)
    try:
        result = run_goal(surface, args.goal, max_steps=args.max_steps)
    finally:
        surface.close()

    print("\n" + "=" * 50)
    print(f"SUCCESS: {result.success}")
    print(f"OUTPUTS: {json.dumps(result.outputs, indent=2)}")
    print(f"REASON:  {result.reason}")
    print(f"STEPS:   {result.steps}")
    print(f"EVIDENCE: {result.evidence_dir}")
    print("=" * 50)


if __name__ == "__main__":
    main()