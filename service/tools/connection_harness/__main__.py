import argparse
import json
from pathlib import Path

from .simulation import replay, scenario


def main():
    parser = argparse.ArgumentParser(description="Mesh Chat connection qualification")
    commands = parser.add_subparsers(dest="command", required=True)
    simulate = commands.add_parser("simulate")
    simulate.add_argument("--scenario", choices=("stale_completion", "partition_30s", "fault_sequence"), required=True)
    simulate.add_argument("--seed", type=int, default=42)
    simulate.add_argument("--output", type=Path)
    repeat = commands.add_parser("replay")
    repeat.add_argument("--trace", type=Path, required=True)
    repeat.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "replay":
        if args.trace.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Trace exceeds the four-MiB input budget")
        evidence = replay(json.loads(args.trace.read_text(encoding="utf-8")))
    else:
        evidence = scenario(args.scenario, args.seed)
    encoded = json.dumps(evidence, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
