"""CLI: no cluster connectivity, no subprocesses, no secret handling."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .inputs import InputError, import_kubernetes, load_json
from .planner import plan
from .report import to_json, to_sarif, to_text


def _write(path: str | None, body: str) -> None:
    if path is None or path == "-":
        sys.stdout.write(body)
        return
    dest = Path(path)
    if dest.is_symlink():
        raise InputError("refusing output through symlink")
    if dest.is_dir():
        raise InputError("output path is a directory")
    dest.write_text(body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pdbguard", description="Offline Kubernetes maintenance wave and PDB analysis")
    parser.add_argument("--version", action="version", version=f"pdbguard {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("import", help="Convert kubectl node/pod/PDB JSON lists into a minimized snapshot")
    for name in ("nodes", "pods", "pdbs"):
        ingest.add_argument("--" + name, required=True, help="kubectl get -o json list")
    ingest.add_argument("--out", default="-", help="JSON snapshot path, or - for stdout")
    inspect = sub.add_parser("plan", help="Find maximal eligible concurrent drain wave (advisory only)")
    inspect.add_argument("snapshot", help="snapshot produced by pdbguard import")
    inspect.add_argument("--nodes", nargs="+", required=True, help="target node names (up to 18)")
    inspect.add_argument("--format", choices=("text", "json", "sarif"), default="text")
    inspect.add_argument("--out", default="-", help="report path, or - for stdout")
    inspect.add_argument("--allow-missing-pdb", action="store_true", help="warn, rather than block, if a Pod has no PDB")
    inspect.add_argument("--ack-emptydir-loss", action="store_true", help="warn rather than block on emptyDir data loss")
    inspect.add_argument("--ack-unmanaged", action="store_true", help="warn rather than block on unmanaged Pods")
    inspect.add_argument("--min-ready-nodes-per-zone", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            snapshot = import_kubernetes(load_json(args.nodes), load_json(args.pods), load_json(args.pdbs))
            _write(args.out, json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
            return 0
        snapshot = load_json(args.snapshot)
        report = plan(snapshot, args.nodes, require_pdb=not args.allow_missing_pdb,
                      allow_emptydir=args.ack_emptydir_loss, allow_unmanaged=args.ack_unmanaged,
                      min_nodes_per_zone=args.min_ready_nodes_per_zone)
        formats = {"text": to_text, "json": to_json, "sarif": to_sarif}
        _write(args.out, formats[args.format](report))
        return 0 if report["summary"]["complete"] else 1
    except (InputError, OSError, ValueError) as exc:
        print(f"pdbguard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
