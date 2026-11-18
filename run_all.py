"""Run the whole geometry pipeline in order.
Usage:
  python run_all.py                           # uses config.json
  python run_all.py --design-pack design_pack/panter_v1.json  # loads design pack, writes config.json + render_args.json
Extra args after '--' are passed to each step (e.g., --z-cut auto --plinth-height 3.0).
"""
import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def load_design_pack(design_pack_path: str) -> int:
    """Run load_design_pack.py to generate config.json and render_args.json."""
    script = os.path.join(HERE, "load_design_pack.py")
    cmd = [PY, script, design_pack_path]
    print(f"==> Loading design pack: {design_pack_path}", flush=True)
    r = subprocess.run(cmd, cwd=HERE, env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    return r.returncode


def run_steps(extra_args: list[str]) -> None:
    steps = [['analyze_case.py'], ['build_case_v2.py'], ['build_stand.py'], ['make_report.py']]
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    for st in steps:
        print('==>', ' '.join(st), flush=True)
        r = subprocess.run([PY, os.path.join(HERE, st[0])] + st[1:] + extra_args, cwd=HERE, env=env)
        if r.returncode != 0:
            sys.exit(f'step failed: {st}')
    print('all steps OK')


def main():
    ap = argparse.ArgumentParser(description="Run full geometry pipeline", add_help=False)
    ap.add_argument("--design-pack", help="Path to design_pack JSON (relative to project root or absolute)")
    ap.add_argument("--help", action="store_true", help="Show help")
    # Parse known args to separate --design-pack from step args
    args, step_args = ap.parse_known_args()

    if args.help:
        print(__doc__)
        sys.exit(0)

    if args.design_pack:
        # Resolve path relative to project root
        if not os.path.isabs(args.design_pack):
            project_root = os.path.dirname(os.path.dirname(HERE))
            design_pack_path = os.path.join(project_root, args.design_pack)
        else:
            design_pack_path = args.design_pack
        if not os.path.exists(design_pack_path):
            sys.exit(f"Design pack not found: {design_pack_path}")
        rc = load_design_pack(design_pack_path)
        if rc != 0:
            sys.exit(f"load_design_pack.py failed with code {rc}")

    run_steps(step_args)


if __name__ == "__main__":
    main()
